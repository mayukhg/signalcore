import json, pathlib
h = pathlib.Path(__file__).parent
t = (h / "prototype.template.html").read_text()
t = t.replace("/*__DATA__*/null", (h / "app_data.json").read_text().replace("</", "<\\/"))
t = t.replace("/*__DDL__*/null", json.dumps((h / "schema.sql").read_text()).replace("</", "<\\/"))
(h / "signalcore-prototype.html").write_text(t)
