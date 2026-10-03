-- Schema only; do not import the content or DROP TABLE from backup/table_dump.sql.
CREATE TABLE IF NOT EXISTS text_box (
  box varchar(255) NOT NULL,
  pie varchar(255) NOT NULL,
  text text,
  title varchar(255) DEFAULT NULL,
  PRIMARY KEY (box, pie)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
