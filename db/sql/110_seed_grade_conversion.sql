-- 110 — seed the observed dataGrade ladder (knowledge/data/grade-conversion.md).
-- Calibrated to the Diff→E1 multi-pitch trad band; extend at the extremes
-- deliberately and log it in the decision log.
SET search_path = climbing, public;

INSERT INTO grade_conversion (grade_system_code, original_grade, data_grade) VALUES
    -- dataGrade 1
    ('BAS', 'D 3a',  1), ('BAS', 'D 3b',  1),
    -- dataGrade 2
    ('BAS', 'VD 3c', 2), ('UIAA', 'IV−',  2),
    -- dataGrade 3
    ('BAS', 'S 3c',  3), ('BAS', 'S 4a',  3), ('BAS', 'S 4b', 3),
    ('YDS', '5.7',   3), ('FS',  'f4c',   3),
    -- dataGrade 4
    ('BAS', 'HS 4a', 4), ('BAS', 'HS 4b', 4), ('UIAA', 'IV+', 4), ('ALP', 'D', 4),
    -- dataGrade 5
    ('BAS', 'VS 4b', 5), ('BAS', 'VS 4c', 5), ('BAS', 'VS 5a', 5),
    ('UIAA', 'V+',   5), ('YDS', '5.8',   5), ('FS',  'f5a',   5),
    -- dataGrade 6
    ('BAS', 'HVS 5b', 6), ('BAS', 'HVS 5c', 6),
    -- dataGrade 7
    ('BAS', 'E1 5b', 7), ('UIAA', 'VI+', 7), ('ALP', 'TD', 7),
    ('FS',  'f6b',   7), ('N',   'N6−',  7);
