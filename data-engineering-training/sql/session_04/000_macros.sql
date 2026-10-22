-- Presentation and effective-date helpers. They do not decide grain.
CREATE OR REPLACE MACRO title_case(value) AS (
    CASE
        WHEN value IS NULL OR TRIM(CAST(value AS VARCHAR)) = '' THEN NULL
        ELSE array_to_string(
            list_transform(
                string_split(TRIM(CAST(value AS VARCHAR)), ' '),
                word -> CASE
                    WHEN word = '' THEN ''
                    ELSE UPPER(LEFT(word, 1)) || LOWER(SUBSTR(word, 2))
                END
            ),
            ' '
        )
    END
);

-- A version covers a calendar date when the date is inside
-- [effective_from, effective_to]. An open version has no effective_to.
CREATE OR REPLACE MACRO version_covers(effective_from, effective_to, on_date) AS (
    on_date >= effective_from
    AND (effective_to IS NULL OR on_date <= effective_to)
);
