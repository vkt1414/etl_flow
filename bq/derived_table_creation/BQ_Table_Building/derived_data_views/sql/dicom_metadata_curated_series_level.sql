WITH
  temp_table AS (
  SELECT
    dicom_all.SeriesInstanceUID,
    ANY_VALUE(Modality) AS Modality,
    STRING_AGG(DISTINCT(collection_id),",") AS collection_id,
    ANY_VALUE(OpticalPathSequence[SAFE_OFFSET(0)].ObjectiveLensPower) AS ObjectiveLensPower,
    MAX(DISTINCT(TotalPixelMatrixColumns)) AS max_TotalPixelMatrixColumns,
    MAX(DISTINCT(TotalPixelMatrixRows)) AS max_TotalPixelMatrixRows,
    MAX(DISTINCT(`Columns`)) AS max_Columns,
    MAX(DISTINCT(`Rows`)) AS max_Rows,
    MIN(DISTINCT(SAFE_CAST(PixelSpacing[SAFE_OFFSET(0)] AS FLOAT64))) AS min_spacing_0,
    MIN(DISTINCT(SAFE_CAST(PixelSpacing[SAFE_OFFSET(1)] AS FLOAT64))) AS min_spacing_1,
    MIN(SAFE_CAST(SharedFunctionalGroupsSequence[SAFE_OFFSET(0)].PixelMeasuresSequence[SAFE_OFFSET(0)]. PixelSpacing[SAFE_OFFSET(0)] AS FLOAT64)) AS fg_min_spacing_0,
    MIN(SAFE_CAST(SharedFunctionalGroupsSequence[SAFE_OFFSET(0)].PixelMeasuresSequence[SAFE_OFFSET(0)]. PixelSpacing[SAFE_OFFSET(1)] AS FLOAT64)) AS fg_min_spacing_1,
    ARRAY_AGG(DISTINCT(CONCAT(SpecimenDescriptionSequence[SAFE_OFFSET(0)].PrimaryAnatomicStructureSequence[SAFE_OFFSET(0)].CodeValue,",", SpecimenDescriptionSequence[SAFE_OFFSET(0)].PrimaryAnatomicStructureSequence[SAFE_OFFSET(0)].CodingSchemeDesignator,",", SpecimenDescriptionSequence[SAFE_OFFSET(0)].PrimaryAnatomicStructureSequence[SAFE_OFFSET(0)].CodeMeaning )) IGNORE NULLS) AS primaryAnatomicStructure,
    ARRAY_AGG(DISTINCT(CONCAT(OpticalPathSequence[SAFE_OFFSET(0)].IlluminationTypeCodeSequence[SAFE_OFFSET(0)].CodeValue,",", OpticalPathSequence[SAFE_OFFSET(0)].IlluminationTypeCodeSequence[SAFE_OFFSET(0)].CodingSchemeDesignator,",", OpticalPathSequence[SAFE_OFFSET(0)].IlluminationTypeCodeSequence[SAFE_OFFSET(0)].CodeMeaning )) IGNORE NULLS) AS illuminationType,
  FROM
    `idc-dev-etl.idc_v13_pub.dicom_all` AS dicom_all
  GROUP BY
    SeriesInstanceUID
  )
SELECT
  SeriesInstanceUID,
  COALESCE(min_spacing_0, fg_min_spacing_0) AS min_PixelSpacing0,
  COALESCE(max_TotalPixelMatrixColumns, max_Columns) AS max_TotalPixelMatrixColumns,
  COALESCE(max_TotalPixelMatrixRows, max_Rows) AS max_TotalPixelMatrixRows,
  ObjectiveLensPower,
  primaryAnatomicStructure,
  illuminationType,
  Modality,
FROM
  temp_table