"""One conversion per child process: enforce wall time in the parent service."""
import io
import json
import sys

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

options = json.loads(sys.argv[2])
pipeline = PdfPipelineOptions()
pipeline.do_ocr = False  # Native text/layout only; existing OCR remains the fallback.
pipeline.do_table_structure = True
pipeline.document_timeout = 150
converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(
    pipeline_options=pipeline)})
with open(sys.argv[1], "rb") as source:
    result = converter.convert(DocumentStream(name="source.pdf", stream=io.BytesIO(source.read())),
                               max_num_pages=100, max_file_size=50 * 1024 * 1024,
                               page_range=(options["page_start"], options["page_end"]))
doc = result.document
text = "\n\n".join(f"## Page {number}\n{doc.export_to_markdown(page_no=number)}"
                      for number in sorted(doc.pages))
tables = []
for table in doc.tables[:30]:
    tables.append({"provenance": [p.model_dump(mode="json") for p in table.prov],
                   "data": table.data.model_dump(mode="json")})
json.dump({"text": text, "tables": tables, "status": result.status.value,
           "pages": sorted(doc.pages), "tables_total": len(doc.tables)}, sys.stdout)
