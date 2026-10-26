/* =====================================================================
   MedMind - Sprint "Database Completion"  |  Script 06: ERD export
   READ-ONLY. Builds the ERD from the LIVE schema, so it can never drift
   from the database. Output = one row per line of a Mermaid erDiagram.

   HOW TO USE
   1. Run this script in the final database (after scripts 01-03).
   2. In SSMS: Results to Grid, select the whole 'line' column, copy, and paste
      into https://mermaid.live  (or a .mmd file / GitHub markdown ```mermaid block).
   Alternative: SSMS > Database Diagrams, or dbdiagram.io / DBeaver "ER Diagram".
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET NOCOUNT ON;

;WITH rel AS (
    -- one line per foreign key (composite FKs list all their columns)
    SELECT DISTINCT
           pt.name AS parent_table, ct.name AS child_table, fk.name AS fk_name,
           STUFF((SELECT ', ' + cc.name
                  FROM sys.foreign_key_columns fkc2
                  JOIN sys.columns cc ON cc.object_id = fkc2.parent_object_id AND cc.column_id = fkc2.parent_column_id
                  WHERE fkc2.constraint_object_id = fk.object_id
                  ORDER BY fkc2.constraint_column_id
                  FOR XML PATH('')), 1, 2, '') AS child_columns,
           CASE WHEN EXISTS (SELECT 1 FROM sys.foreign_key_columns fkc3
                             JOIN sys.columns cc3 ON cc3.object_id = fkc3.parent_object_id AND cc3.column_id = fkc3.parent_column_id
                             WHERE fkc3.constraint_object_id = fk.object_id AND cc3.is_nullable = 1) THEN 1 ELSE 0 END AS optional_link
    FROM sys.foreign_keys fk
    JOIN sys.tables pt ON pt.object_id = fk.referenced_object_id
    JOIN sys.tables ct ON ct.object_id = fk.parent_object_id
    WHERE ct.name <> 'alembic_version'
), lines AS (
    SELECT 0 AS grp, CAST('0' AS nvarchar(300)) AS sort_key, CAST('erDiagram' AS nvarchar(max)) AS line
    UNION ALL
    -- entity opening line
    SELECT 1, t.name + '|0000', CAST('    ' + t.name + ' {' AS nvarchar(max))
    FROM sys.tables t WHERE t.name <> 'alembic_version'
    UNION ALL
    -- one line per column
    SELECT 1, t.name + '|' + RIGHT('0000' + CAST(c.column_id AS varchar(4)), 4),
           CAST('        ' + REPLACE(REPLACE(REPLACE(ty.name, ' ', '_'), '(', ''), ')', '') + ' ' + c.name
           + CASE WHEN EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                               WHERE i.is_primary_key = 1 AND ic.object_id = c.object_id AND ic.column_id = c.column_id) THEN ' PK'
                  WHEN EXISTS (SELECT 1 FROM sys.foreign_key_columns f WHERE f.parent_object_id = c.object_id AND f.parent_column_id = c.column_id) THEN ' FK'
                  ELSE '' END AS nvarchar(max))
    FROM sys.tables t
    JOIN sys.columns c ON c.object_id = t.object_id
    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE t.name <> 'alembic_version'
    UNION ALL
    -- entity closing line
    SELECT 1, t.name + '|9999', CAST('    }' AS nvarchar(max))
    FROM sys.tables t WHERE t.name <> 'alembic_version'
    UNION ALL
    -- relationships (parent 1 -> many children; |o = optional)
    SELECT 2, r.parent_table + '|' + r.child_table + '|' + r.fk_name,
           CAST('    ' + r.parent_table + CASE WHEN r.optional_link = 1 THEN ' |o--o{ ' ELSE ' ||--o{ ' END + r.child_table
           + ' : "' + REPLACE(r.child_columns, ',', ' +') + '"' AS nvarchar(max))
    FROM rel r
)
SELECT line
FROM lines
ORDER BY grp, sort_key;
GO
SET NOEXEC OFF;
GO
