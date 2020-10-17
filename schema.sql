-- Postgres SQL has been used for Database management
-- To create the database:
--   CREATE DATABASE blog;
--   CREATE USER blog WITH PASSWORD 'blog';
--   GRANT ALL ON DATABASE blog TO blog;

DROP TABLE IF EXISTS authors;
CREATE TABLE authors (
    id SERIAL PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    hashed_password VARCHAR(100) NOT NULL
);

DROP TABLE IF EXISTS entries;
CREATE TABLE entries (
    id SERIAL PRIMARY KEY,
    author_id INT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(512) NOT NULL,
    markdown TEXT NOT NULL,
    html TEXT NOT NULL,
    comments TEXT DEFAULT :,
    published TIMESTAMP NOT NULL,
    updated TIMESTAMP NOT NULL,
    image_flag BOOLEAN DEFAULT FALSE
);

DROP TABLE IF EXISTS votes;
CREATE TABLE votes (
    id INT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    author_id INT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    vote INT DEFAULT 0,
    slug VARCHAR(100) NOT NULL REFERENCES entries(slug) ON DELETE CASCADE,
    primary key(id,author_id)
);

CREATE INDEX ON entries (published);
