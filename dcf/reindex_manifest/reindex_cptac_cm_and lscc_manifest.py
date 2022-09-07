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


# Generate a reindex manifest of CPTAC-CM and CPTAC-LSCC pathology
# instance, moving from defaced to open in v11

import argparse
import settings
from uuid import uuid4
from google.cloud import bigquery
from utilities.bq_helpers import query_BQ, export_BQ_to_GCS, delete_BQ_Table

def gen_instance_manifest(args):
    BQ_client = bigquery.Client(project=args.project)
    query = f"""
         SELECT distinct 
            CONCAT('dg.4DFC/', a.i_uuid) as GUID, 
            i_hash as md5, 
            i_size as size, 
            CONCAT('gs://public-datasets-idc/', a.i_uuid, '.dcm') as url
         FROM `idc-dev-etl.{settings.BQ_DEV_INT_DATASET}.all_joined_included` a
         WHERE
            collection_id in {args.collections} 
            AND i_source='path'
            AND i_rev_idc_version < 9
--          AND ((a.i_source='tcia' and i.pub_tcia_url='public-datasets-idc')
--          OR (a.i_source='path' and i.pub_path_url='public-datasets-idc'))
         AND a.i_excluded=FALSE    
    """

    # Run a query that generates the manifest data
    results = query_BQ(BQ_client, args.dst_bqdataset, args.temp_table, query,\
        write_disposition='WRITE_TRUNCATE', expiration=0)

    # Export the resulting table to GCS
    results = export_BQ_to_GCS(BQ_client, args.dst_bqdataset, args.temp_table, args.manifest_uri)

    while results.state == 'RUNNING':
        pass

    delete_BQ_Table(BQ_client, args.project, args.dst_bqdataset, args.temp_table)

if __name__ == '__main__':
    version = settings.CURRENT_VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default=settings.DEV_PROJECT)
    parser.add_argument('--src_bqdataset', default=settings.BQ_PUB_DATASET, \
            help='BQ dataset containing the auxiliary_metadata table from which to get gcs_urls')
    parser.add_argument('--dst_bqdataset', default=settings.BQ_DEV_INT_DATASET, \
            help='BQ dataset in which to build the temporary table')
    # parser.add_argument('--versions', default=f'({settings.CURRENT_VERSION})', \
    #         help= 'A quoted tuple of version numbers, e.g. "(1,2)"')
    parser.add_argument('--version', default={settings.CURRENT_VERSION})
    parser.add_argument('--collections', default="('CPTAC-CM', 'CPTAC-LSCC')", \
            help= 'A quoted tuple of collection ids, e.g. "(\'CPTAC-GBM\', \'TCGA-GBM\')"')
    parser.add_argument('--manifest_uri', default=f'gs://indexd_manifests/dcf_input/pdp_hosting/idc_v{settings.CURRENT_VERSION}_reindex_cptac_cm_and_lscc_pathology_manifest_*.tsv',
            help="GCS blob in which to save results")
    # parser.add_argument('--temp_table', default=f'idc_v{settings.CURRENT_VERSION}_instance_manifest', \
    parser.add_argument('--temp_table', default=str(uuid4()), \
                        help='Temporary table in which to write query results')
    args = parser.parse_args()

    gen_instance_manifest(args)