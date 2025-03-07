#!/usr/bin/env
#
# Copyright 2020, Institute for Systems Biology
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

import argparse
import sys
from bq.gen_original_data_collections_table.gen_original_data_collection_metadata_table import gen_collections_table
from python_settings import settings


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # parser.add_argument('--version', default=8, help='IDC version for which to build the table')
    # args = parser.parse_args()
    # parser.add_argument('--src_project', default='idc-dev-etl')
    # parser.add_argument('--dst_project', default='idc-dev-etl')
    # parser.add_argument('--dev_bqdataset_name', default=f'idc_v{args.version}_dev', help='BQ dataset of dev tables')
    # parser.add_argument('--pub_bqdataset_name', default=f'idc_v{args.version}_pub', help='BQ dataset of public tables')
    parser.add_argument('--bqtable_name', default='original_collections_metadata', help='BQ table name')
    parser.add_argument('--access', default='Public', help="Generate excluded_original_collections_metadata if True")
    parser.add_argument('--use_cached_metadata', default=False)
    parser.add_argument('--cached_metadata_file', default='cached_included_metadata.json', help='Where to cache metadata')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)
    gen_collections_table(args)