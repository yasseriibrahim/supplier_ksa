"""Run with Odoo shell to provision the invoice source locations."""

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
company = admin.company_id
warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
if not warehouse:
    raise RuntimeError("The current company has no stock warehouse")

# Clean up records created under the technical shell user's company by an
# earlier run of this provisioning script. Only untouched, empty locations
# with the exact requested names are considered.
misplaced = env["stock.location"].search([
    ("name", "in", ("مخزن جده", "مخزن الدمام")),
    ("company_id", "!=", company.id),
])
for location in misplaced:
    has_quants = bool(env["stock.quant"].search_count([("location_id", "child_of", location.id)]))
    has_moves = bool(env["stock.move"].search_count([
        "|", ("location_id", "child_of", location.id),
        ("location_dest_id", "child_of", location.id),
    ]))
    if not has_quants and not has_moves:
        location.unlink()

for location_name in ("مخزن جده", "مخزن الدمام"):
    location = env["stock.location"].search([
        ("name", "=", location_name),
        ("location_id", "=", warehouse.lot_stock_id.id),
        ("company_id", "=", company.id),
    ], limit=1)
    if not location:
        location = env["stock.location"].create({
            "name": location_name,
            "usage": "internal",
            "location_id": warehouse.lot_stock_id.id,
            "company_id": company.id,
        })
    print("LOCATION", location.id, location.complete_name, location.company_id.display_name)

env.cr.commit()
