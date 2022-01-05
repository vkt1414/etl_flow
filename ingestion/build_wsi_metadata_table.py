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

# Build a table of collection/patient/study/series/instance metadata for the WSIs
# Assumes that bucket containing the pathology WSI blobs is gcsfuse mounted (the
# mount point is a paramater). This allows pydicom that extract DICOM UIDs
# from each blob without having to import the entire (large) blob.

import os
import sys
import argparse
import pydicom

from idc.models import Base, WSI_Collection, WSI_Patient, WSI_Study, WSI_Series, WSI_Instance
from ingestion.utils import get_merkle_hash

from google.cloud import storage


import logging
from logging import INFO, DEBUG
from base64 import b64decode
import settings as etl_settings
from python_settings import settings
settings.configure(etl_settings)

from sqlalchemy.orm import Session
from sqlalchemy import create_engine, update
from google.cloud import storage


def list_blobs_with_prefix(bucket, prefix, delimiter=None):
    # storage_client = storage.Client()
    # bucket = storage_client.bucket(args.src_bucket)
    blobs = args.client.list_blobs(bucket, prefix=prefix, delimiter=delimiter)
    names = [blob.name for blob in blobs]
    ids = [ prefix.split('/')[-2] for prefix in blobs.prefixes]
    ids.sort()
    return blobs, ids

def build_instances(client, args, sess, series, prefix):
    blobs = client.list_blobs(args.src_bucket, prefix=prefix, delimiter=None)
    for blob in blobs:
        instance_id = blob.name.rsplit('/',1)[-1].split('.dcm')[0]
        instance = sess.query(WSI_Instance).filter(WSI_Instance.sop_instance_uid == instance_id).first()
        if not instance:
            instance = WSI_Instance()
            instance.sop_instance_uid = instance_id
            instance.series_instance_uid = series.series_instance_uid
            instance.url = f'gs://{args.src_bucket.name}/{blob.name}'
            series.instances.append(instance)
            # sess.commit()
        instance.hash = b64decode(blob.md5_hash).hex()


def build_series(client, args, sess, study, prefix):
    _, series_ids = list_blobs_with_prefix(args.src_bucket, prefix=prefix, delimiter='/')
    for series_id in series_ids:
        series = sess.query(WSI_Series).filter(WSI_Series.series_instance_uid == series_id).first()
        if not series:
            series = WSI_Series()
            series.series_instance_uid = series_id
            series.study_instance_uid = study.study_instance_uid
            study.seriess.append(series)
            # sess.commit()
        build_instances(client, args, sess, series, f'{prefix}{series_id}/')
        hashes = [instance.hash for instance in series.instances]
        series.hash = get_merkle_hash(hashes)


def build_studies(client, args, sess, patient, prefix):
    _, study_ids= list_blobs_with_prefix(args.src_bucket, prefix=prefix, delimiter='/')
    for study_id in study_ids:
        study = sess.query(WSI_Study).filter(WSI_Study.study_instance_uid == study_id).first()
        if not study:
            study = WSI_Study()
            study.study_instance_uid = study_id
            study.submitter_case_id = patient.submitter_case_id
            patient.studies.append(study)
            # sess.commit()
        build_series(client, args, sess, study, f'{prefix}{study_id}/')
        hashes = [series.hash for series in study.seriess]
        study.hash = get_merkle_hash(hashes)


def build_patients(client, args, sess, collection, prefix):
    _, patient_ids= list_blobs_with_prefix(args.src_bucket, prefix=prefix, delimiter='/')
    for patient_id in patient_ids:
        patient = sess.query(WSI_Patient).filter(WSI_Patient.submitter_case_id == patient_id).first()
        if not patient:
            patient = WSI_Patient()
            patient.submitter_case_id = patient_id
            patient.collection_id = collection.collection_id
            collection.patients.append(patient)
            # sess.commit()
        build_studies(client, args, sess, patient, f'{prefix}{patient_id}/')
        hashes = [study.hash for study in patient.studies]
        patient.hash = get_merkle_hash(hashes)


def build_collections(client, args, sess):
    try:
        dones = open(args.dones).read().splitlines()
    except:
        dones = []

    _, collection_ids = list_blobs_with_prefix(args.src_bucket, prefix=None, delimiter='/')
    for collection_id in collection_ids:
        if not collection_id in dones:
            rootlogger.info('Collecting metadata from collection %s', collection_id)
            collection = sess.query(WSI_Collection).filter(WSI_Collection.collection_id == collection_id).first()
            if not collection:
                collection = WSI_Collection()
                collection.collection_id = collection_id
                sess.add(collection)
                # sess.commit()
            build_patients(client, args, sess, collection, f'{collection_id}/')
            hashes = [patient.hash for patient in collection.patients]
            collection.hash = get_merkle_hash(hashes)
            sess.commit()

            with open(args.dones, 'a') as f:
                f.write(f'{collection_id}\n')

def prebuild(args):
    sql_uri = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/{args.db}'
    # sql_engine = create_engine(sql_uri, echo=True)
    sql_engine = create_engine(sql_uri)
    # Create the tables if they do not already exist
    Base.metadata.create_all(sql_engine)

    # todos = open(args.todos).read().splitlines()

    with Session(sql_engine) as sess:
        client = storage.Client()
        build_collections(client, args, sess)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default=7, help='Version to work on')
    parser.add_argument('--client', default=storage.Client())
    args = parser.parse_args()
    parser.add_argument('--db', default=f'idc_v{args.version}', help='Database on which to operate')
    parser.add_argument('--project', default='idc-dev-etl')
    parser.add_argument('--gcsfuse_dir', default='/mnt/disks/idc-etl/wsi_bucket')
    parser.add_argument('--src_bucket', default=storage.Bucket(args.client,'dac-wsi-conversion-results-v2-sorted'))
    parser.add_argument('--num_processes', default=0, help="Number of concurrent processes")
    # parser.add_argument('--todos', default='{}/logs/path_ingest_v{}_todo.txt'.format(os.environ['PWD'], args.version), help="Collections to include")
    parser.add_argument('--dones', default='{}/logs/wsi_build_dones.txt'.format(os.environ['PWD']), help="Completed collections")
    args = parser.parse_args()

    print("{}".format(args), file=sys.stdout)

    rootlogger = logging.getLogger('root')
    root_fh = logging.FileHandler('{}/logs/wsi_metadata_log.log'.format(os.environ['PWD'], args.version))
    rootformatter = logging.Formatter('%(levelname)s:root:%(message)s')
    rootlogger.addHandler(root_fh)
    root_fh.setFormatter(rootformatter)
    rootlogger.setLevel(DEBUG)

    errlogger = logging.getLogger('root.err')
    err_fh = logging.FileHandler('{}/logs/wsi_metadata_err.log'.format(os.environ['PWD'], args.version))
    errformatter = logging.Formatter('{%(pathname)s:%(lineno)d} %(levelname)s:err:%(message)s')
    errlogger.addHandler(err_fh)
    err_fh.setFormatter(errformatter)

    # rootlogger.info('Args: %s', args)
    prebuild(args)
