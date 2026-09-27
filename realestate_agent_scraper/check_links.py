import re
html = open('debug_output/page_html.html', encoding='utf-8').read()

# Find agent-related hrefs
print("=== Links with /agent/ ===")
matches = re.findall(r'href="([^"]*?/agent/[^"]*?)"', html)
for m in matches[:20]:
    print(m)

print("\n=== Links with find-agent ===")
matches = re.findall(r'href="([^"]*?find-agent[^"]*?)"', html)
for m in matches[:20]:

    print(m)

print("\n=== Links with salesperson ===")
matches = re.findall(r'href="([^"]*?salesperson[^"]*?)"', html)
for m in matches[:10]:
    print(m)

# Check for agent data in JSON
print("\n=== Agent JSON data (first few) ===")
names = re.findall(r'"name":"([^"]+)"', html)[:10]
ids = re.findall(r'"salespersonId":"(\d+)"', html)[:10]
for n, i in zip(names, ids):
    print(f"  {n} (ID: {i})")

# Check profile URL patterns
print("\n=== Profile URL patterns ===")
profiles = re.findall(r'"profileUrl":"([^"]+)"', html)[:10]
for p in profiles:
    print(f"  {p}")
