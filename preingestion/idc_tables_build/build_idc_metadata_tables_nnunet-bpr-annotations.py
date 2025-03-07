#
# Copyright 2015-2021, Institute for Systems Biology
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Adds/replaces data to the idc_collection/_patient/_study/_series/_instance DB tables
# for the nnunet-bpr-annotations data set, https://zenodo.org/record/7473971
#
# For this purpose, the bucket containing the instance blobs is gcsfuse mounted, and
# pydicom is then used to extract needed metadata.

import io
import os
import sys
import argparse
import csv
import subprocess
from idc.models import Base, IDC_Collection, IDC_Patient, IDC_Study, IDC_Series, IDC_Instance
from ingestion.utilities.utils import get_merkle_hash, list_skips

from logging import INFO, DEBUG
from utilities.logging_config import successlogger, errlogger, progresslogger
from base64 import b64decode
from python_settings import settings

from pydicom import dcmread

from sqlalchemy.orm import Session
from sqlalchemy import create_engine, update
from google.cloud import storage

def build_instance(client, args, sess, series, instance_id, hash, blob_name):
    try:
        # Get the record of this instance if it exists
        instance = next(instance for instance in series.instances if instance.sop_instance_uid == instance_id)
    except StopIteration:
        instance = IDC_Instance()
        instance.sop_instance_uid = instance_id
        series.instances.append(instance)
    # Always set/update these values
    if instance.hash != hash:
        # Revise this instance's version
        instance.idc_version = args.version
        instance.gcs_url = f'gs://{args.src_bucket}/{blob_name}'
        instance.hash = hash

    # blob_name = f'{args.src_path}/{row["Filename"].strip()}' if args.src_path else \
    #     f'{row["Filename"].strip().split("/", 1)[1]}'
    # instance.url = f'gs://{args.src_bucket}/{blob_name}'
    # bucket = client.bucket(args.src_bucket)
    # blob = bucket.blob(blob_name)
    # blob.reload()
    # new_hash = b64decode(blob.md5_hash).hex()

    successlogger.info(blob_name)


def build_series(client, args, sess, study, series_id, doi, instance_id, hash, blob_name):
    try:
        series = next(series for series in study.seriess if series.series_instance_uid == series_id)
    except StopIteration:
        series = IDC_Series()
        series.series_instance_uid = series_id
        series.license_url =args.license['license_url']
        series.license_long_name =args.license['license_long_name']
        series.license_short_name =args.license['license_short_name']
        study.seriess.append(series)
    # Always set/update the wiki_doi in case it has changed
    series.wiki_doi = doi
    series.wiki_url = f'https://doi.org/{doi}'
    series.third_party = args.third_party
    build_instance(client, args, sess, series, instance_id, hash, blob_name)
    return


def build_study(client, args, sess, patient, study_id, series_id, doi, instance_id, hash, blob_name):
    try:
        study = next(study for study in patient.studies if study.study_instance_uid == study_id)
    except StopIteration:
        study = IDC_Study()
        study.study_instance_uid = study_id
        patient.studies.append(study)
    build_series(client, args, sess, study, series_id, doi, instance_id, hash, blob_name)
    return


def build_patient(client, args, sess, collection, patient_id, study_id, series_id, doi, instance_id, hash, blob_name):
    try:
        patient = next(patient for patient in collection.patients if patient.submitter_case_id == patient_id)
    except StopIteration:
        patient = IDC_Patient()
        patient.submitter_case_id = patient_id
        collection.patients.append(patient)
    build_study(client, args, sess, patient, study_id, series_id, doi, instance_id, hash, blob_name)
    return


def build_collection(client, args, sess, collection_id, patient_id, study_id, series_id, doi, instance_id, hash, blob_name):
    collection = sess.query(IDC_Collection).filter(IDC_Collection.collection_id == collection_id).first()
    if not collection:
        # The collection is not currently in the DB, so add it
        collection = IDC_Collection()
        collection.collection_id = collection_id
        sess.add(collection)
    build_patient(client, args, sess, collection, patient_id, study_id, series_id, doi, instance_id, hash, blob_name)
    return


def prebuild(args):
    client = storage.Client()
    src_bucket = storage.Bucket(client, args.src_bucket)

    dones = set(open(f'{successlogger.handlers[0].baseFilename}').read().splitlines())

    sql_uri = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/{settings.CLOUD_DATABASE}'
    # sql_engine = create_engine(sql_uri, echo=True)
    sql_engine = create_engine(sql_uri)

    with Session(sql_engine) as sess:
        client = storage.Client()

        iterator = client.list_blobs(src_bucket)
        for page in iterator.pages:
            if page.num_items:
                for blob in page:
                    if not blob.name in dones:
                        if blob.name.endswith('.dcm'):
                            parts = blob.name.split('/')
                            collection_id = args.collection_map[parts[0]]['collection_id']
                            doi = args.collection_map[parts[0]]['doi']
                            with open(f"{args.mount_point}/{blob.name}", 'rb') as f:
                                try:
                                    r = dcmread(f)
                                    patient_id = r.PatientID
                                    study_id = r.StudyInstanceUID
                                    series_id = r.SeriesInstanceUID
                                    instance_id = r.SOPInstanceUID
                                except Exception as exc:
                                    print(f'pydicom failed for {blob.name}: {exc}')
                            try:
                                assert patient_id == parts[2]
                            except:
                                errlogger.error(f'patient_id: {patient_id}, parts[2]: {parts[2]}')
                                continue
                            try:
                                assert study_id == parts[3]
                            except:
                                errlogger.error(f'study_id: {study_id}, parts[3]: {parts[3]}')
                                continue
                            hash = b64decode(blob.md5_hash).hex()
                            build_collection(client, args, sess, collection_id, patient_id, study_id, series_id, doi, instance_id, hash, blob.name)
                    else:
                        progresslogger.info(f'Skipped {blob.name}')

        sess.commit()
        return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--version', default=settings.CURRENT_VERSION)
    parser.add_argument('--src_bucket', default='nnunet-bpr-annotations', help='Bucket containing WSI instances')
    parser.add_argument('--collection_map', default={'nlst': {"collection_id": "NLST", "doi": "10.5281/zenodo.7539035"}, \
            'nsclc': {"collection_id": "NSCLC-Radiomics", "doi": "10.5281/zenodo.7539035"}})
    parser.add_argument('--mount_point', default='/mnt/disks/idc-etl/nnunet-bpr-annotations', help='Directory on which to mount the bucket')
    parser.add_argument('--skipped_collections', type=str, default=[], nargs='*', \
      help='A list of additional collections that should not be ingested.')
    parser.add_argument('--license', default = {"license_url": "https://creativecommons.org/licenses/by/4.0",\
            "license_long_name": "Creative Commons Attribution 4.0 International License", \
            "license_short_name": "CC BY 4.0"})
    parser.add_argument('--third_party', type=bool, default=True, help='True if from a third party analysis result')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)
    args.client=storage.Client()

    try:
        # gcsfuse mount the bucket
        subprocess.run(['gcsfuse', '--implicit-dirs', args.src_bucket, args.mount_point])
        prebuild(args)
    finally:
        # Always unmount
        subprocess.run(['fusermount', '-u', args.mount_point])

