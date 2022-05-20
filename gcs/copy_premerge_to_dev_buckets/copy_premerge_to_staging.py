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

# Copy pre-staging buckets populated by ingestion to staging buckets.
# Ingestion copies data into prestaging buckets named by version and
# collection, e.g. idc_v9_path_tcga_brca. The data in these buckets must be
# copied to one of the idc-dev-etl staging buckets:
# idc-dev-open, idc-dev-cr, idc-dev-defaced, idc-dev-redacted, idc-dev-excluded.

import os
import argparse
import logging
from logging import INFO

import settings
from google.cloud import storage, bigquery
from gcs.copy_bucket_mp.copy_bucket_mp import pre_copy

def get_collection_groups():
    client = bigquery.Client()
    collections = {}
    query = f"""
    SELECT idc_webapp_collection_id, dev_tcia_url, dev_path_url
    FROM `idc-dev-etl.{settings.BQ_DEV_INT_DATASET}.all_included_collections`
    """

    result = client.query(query).result()
    for row in result:
        collections[row['idc_webapp_collection_id']] = {"dev_tcia_url": row["dev_tcia_url"], "dev_path_url": row["dev_path_url"]}

    return collections


def copy_prestaging_to_staging(args, prestaging_bucket, staging_bucket):
    print(f'Copying {prestaging_bucket} to {staging_bucket}')
    args.src_bucket = prestaging_bucket
    args.dst_bucket = staging_bucket
    pre_copy(args)
    return


def copy_dev_buckets(args):
    client = storage.Client()
    bucket_data= get_collection_groups()
    for collection_id in bucket_data:
        if client.bucket(f'idc_v{args.version}_tcia_{collection_id}').exists():
            copy_prestaging_to_staging(args, f'idc_v{args.version}_tcia_{collection_id}', bucket_data[collection_id]['dev_tcia_url'])
        if client.bucket(f'idc_v{args.version}_path_{collection_id}').exists():
            copy_prestaging_to_staging(args, f'idc_v{args.version}_path_{collection_id}', bucket_data[collection_id]['dev_path_url'])
    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default=settings.CURRENT_VERSION, help='Version to work on')
    parser.add_argument('--processes', default=16, help="Number of concurrent processes")
    parser.add_argument('--batch', default=100, help='Size of batch assigned to each process')
    parser.add_argument('--log_dir', default=f'/mnt/disks/idc-etl/logs/v9/copy_premerge_to_staging_bucket_mp')
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

    copy_dev_buckets(args)