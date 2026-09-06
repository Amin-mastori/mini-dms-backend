from django.db import migrations

FORWARD = """
CREATE FUNCTION documents_refresh_search() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple'::regconfig, COALESCE(NEW.search_text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER document_search_refresh
BEFORE INSERT OR UPDATE OF search_text ON documents_document
FOR EACH ROW EXECUTE FUNCTION documents_refresh_search();
UPDATE documents_document SET search_text = search_text;
"""
REVERSE = """
DROP TRIGGER IF EXISTS document_search_refresh ON documents_document;
DROP FUNCTION IF EXISTS documents_refresh_search();
"""


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]
    operations = [migrations.RunPython(create_trigger, remove_trigger)]
