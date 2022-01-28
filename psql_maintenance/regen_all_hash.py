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

# Update how hashes.all_hash is generate:
# For series, it is the hash of child instance hashes.
# For higher level objects it is the hash of child
# hashes.all_hashes.

import os
import argparse
import logging
import time
from logging import INFO

from idc.models import Base, Version, Collection, Patient, Study, Series
import settings as etl_settings
from python_settings import settings
settings.configure(etl_settings)
from google.cloud import storage
from ingestion.utils import get_merkle_hash

from multiprocessing import Process, Queue, Lock, shared_memory
from queue import Empty

from sqlalchemy import create_engine
from sqlalchemy_utils import register_composites
from sqlalchemy.orm import Session


def update_patient_hash(args, sess):
    patients = sess.query(Patient).all()
    n = 0
    cnt = len(patients)
    for patient in patients:
        patient_hashes = list(patient.hashes)
        prev_hash = patient_hashes[-1]
        hashes = [study.hashes.all_sources for study in patient.studies]
        patient_hashes[-1] = get_merkle_hash(hashes)
        patient.hashes = patient_hashes
        print(f'{n}of{cnt}: Patient {patient.submitter_case_id},  {prev_hash}, {patient_hashes[-1]}  {"Changed" if prev_hash != patient_hashes[-1] else ""}')
        n += 1
    sess.commit()


def update_collection_hash(args, sess):
    collections = sess.query(Collection).all()
    n = 0
    cnt = len(collections)
    for collection in collections:
        collection_hashes = list(collection.hashes)
        prev_hash = collection_hashes[-1]
        hashes = [patient.hashes.all_sources for patient in collection.patients]
        collection_hashes[-1] = get_merkle_hash(hashes)
        collection.hashes = collection_hashes
        print(f'{n}of{cnt}: Collection {collection.collection_id},  {prev_hash}, {collection_hashes[-1]}  {"Changed" if prev_hash != collection_hashes[-1] else ""}')
        n += 1
    sess.commit()


def update_version_hash(args, sess):
    versions = sess.query(Version).all()
    n = 0
    cnt = len(versions)
    for version in versions:
        version_hashes = list(version.hashes)
        prev_hash = version_hashes[-1]
        hashes = [collection.hashes.all_sources for collection in version.collections]
        version_hashes[-1] = get_merkle_hash(hashes)
        version.hashes = version_hashes
        print(f'{n}of{cnt}: Version {version.version},  {prev_hash}, {version_hashes[-1]}   {"Changed" if prev_hash != version_hashes[-1] else ""}')
        n += 1
    sess.commit()

def update_some_series_hashes(args, sess, like):
    seriess = sess.query(Series).filter(Series.uuid.ilike(like + '%')).all()
    n = 0
    cnt = len(seriess)
    changed = 0
    strt = time.time()
    for series in seriess:
        hashes = list(series.hashes)
        series_hashes = list(series.hashes)
        prev_hash = series_hashes[-1]
        hashes = [instance.hash for instance in series.instances]
        series_hashes[-1] = get_merkle_hash(hashes)
        if series.hashes[-1] != series_hashes[-1]:
            series.hashes = series_hashes
            print(f'{like}: {n}of{cnt}: Series {series.series_instance_uid}, {prev_hash}, {series_hashes[-1]} {"Changed" if prev_hash != series_hashes[-1] else ""}')
            changed += 1
            if not changed%100 :
                sess.commit()
                print(f'{like}: {args.id}: Changed {changed}, {time.time() - strt}')
                strt = time.time()
        n+=1
    sess.commit()



def update_study_hash(args, sess, like):
    studies = sess.query(Study).filter(Study.uuid.ilike(like + '%')).all()
    n = 0
    cnt = len(studies)
    for study in studies:
        study_hashes = list(study.hashes)
        prev_hash = study_hashes[-1]
        hashes = [study.hashes.all_sources for study in study.seriess]
        try:
            study_hashes[-1] = get_merkle_hash(hashes)
        except Exception as exc:
            print(f'Merkle hash failed for study {study.study_instance_uid}')
        if study.hashes[-1] != study_hashes[-1]:
            study.hashes = study_hashes
            print(f'{like}: {n}of{cnt}: Study {study.study_instance_uid},  {prev_hash}, {study_hashes[-1]} {"Changed" if prev_hash != study_hashes[-1] else ""}')
        if not n%100:
            print(f'{like}: {n}of{cnt}: Study {study.study_instance_uid},  {prev_hash}, {study_hashes[-1]} {"Changed" if prev_hash != study_hashes[-1] else ""}')
            sess.commit()
        n += 1
    sess.commit()

def update_patient_hash(args, sess, like):
    patients = sess.query(Patient).filter(Patient.uuid.ilike(like + '%')).all()
    n = 0
    cnt = len(patients)
    for patient in patients:
        patient_hashes = list(patient.hashes)
        prev_hash = patient_hashes[-1]
        hashes = [study.hashes.all_sources for study in patient.studies]
        patient_hashes[-1] = get_merkle_hash(hashes)
        if patient.hashes[-1] != patient_hashes[-1]:
            patient.hashes = patient_hashes
            print(f'{n}of{cnt}: Patient {patient.submitter_case_id},  {prev_hash}, {patient_hashes[-1]}  {"Changed" if prev_hash != patient_hashes[-1] else ""}')
        if not n%100:
            print(f'{n}of{cnt}: Patient {patient.submitter_case_id},  {prev_hash}, {patient_hashes[-1]}  {"Changed" if prev_hash != patient_hashes[-1] else ""}')
            sess.commit()
        n += 1
    sess.commit()


def worker(input, args):
    # rootlogger.debug('p%s: Worker starting: args: %s', args.id, args)
    sql_engine = create_engine(args.sql_uri)
    with Session(sql_engine) as sess:
        for more_args in iter(input.get, 'STOP'):
            func, like = more_args
            func(args, sess, like)


def update_some_hashes(args, func, likes):
    processes = []
    # Create queues
    task_queue = Queue()
    done_queue = Queue()

    enqueued_likes = []

    num_processes = min(args.processes, len(likes))

    # Start worker processes
    lock = Lock()
    for process in range(num_processes):
        args.id = likes[process]
        processes.append(Process(target=worker, args=(task_queue, args, )))
        processes[-1].start()

    # Enqueue each patient in the the task queue
    args.id = 0
    for like in likes:
        task_queue.put((func, like))
        enqueued_likes.append(like)

    # Tell child processes to stop
    for process in processes:
        task_queue.put('STOP')

    # Wait for them to stop
    for process in processes:
        process.join()


def update_all_hashes(args):
    sql_uri = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/{args.db}'
    # sql_engine = create_engine(sql_uri, echo=True) # Use this to see the SQL being sent to PSQL
    sql_engine = create_engine(sql_uri)
    # args.sql_uri = sql_uri # The subprocesses need this uri to create their own SQL engine

    # Enable the underlying psycopg2 to deal with composites
    conn = sql_engine.connect()
    register_composites(conn)



    args.sql_uri = sql_uri
    with Session(sql_engine) as sess:
        # update_some_hashes(args, update_some_series_hashes, '0123')
        # update_some_hashes(args, update_some_series_hashes, '4567')
        # update_some_hashes(args, update_some_series_hashes, '89ab')
        # update_some_hashes(args, update_some_series_hashes, 'cdef')
        update_some_hashes(args, update_study_hash, '0123')
        update_some_hashes(args, update_study_hash, '4567')
        update_some_hashes(args, update_study_hash, '89ab')
        update_some_hashes(args, update_study_hash, 'cdef')
        update_some_hashes(args, update_patient_hash, '0123')
        update_some_hashes(args, update_patient_hash, '4567')
        update_some_hashes(args, update_patient_hash, '89ab')
        update_some_hashes(args, update_patient_hash, 'cdef')
        update_collection_hash(args, sess)
        update_version_hash(args, sess)
        # sess.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default=7, help='Version to work on')
    parser.add_argument('--client', default=storage.Client())
    args = parser.parse_args()
    parser.add_argument('--db', default=f'idc_v7', help='Database on which to operate')
    parser.add_argument('--processes', default=16, help="Number of concurrent processes")
    parser.add_argument('--log_dir', default=f'/mnt/disks/idc-etl/logs/copy_prestaging_to_staging_bucket_mp')
    args = parser.parse_args()
    args.id = 0 # Default process ID

    proglogger = logging.getLogger('root.prog')
    prog_fh = logging.FileHandler(f'{os.environ["PWD"]}/logs/bucket.log')
    progformatter = logging.Formatter('%(levelname)s:prog:%(message)s')
    proglogger.addHandler(prog_fh)
    prog_fh.setFormatter(progformatter)
    proglogger.setLevel(INFO)

    successlogger = logging.getLogger('root.success')
    successlogger.setLevel(INFO)

    errlogger = logging.getLogger('root.err')

    update_all_hashes(args)