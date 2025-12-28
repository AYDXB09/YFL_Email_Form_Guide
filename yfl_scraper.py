from datetime import date
from typing import Tuple


async def scrape_all_divisions(*_args) -> Tuple[str, None, str]:
    today = date.today().isoformat()

    html = f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<title>YFL U11 Form Guide</title>
</head>
<body>
<h1>YFL U11 Form Guide</h1>
<p>Generated on {today}</p>
</body>
</html>
"""

    return html, None, f"yfl_u11_form_guide_{today}.html"
