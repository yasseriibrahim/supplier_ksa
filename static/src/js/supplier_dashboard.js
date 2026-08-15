/** @odoo-module **/

import { Component, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class SupplierDashboard extends Component {
    static template = "supplier_ksa.SupplierDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.data = null;
        onWillStart(async () => {
            this.data = await this.orm.call("supplier.dashboard", "get_dashboard_data", []);
        });
    }

    money(value) {
        return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value || 0)} ${this.data.currency}`;
    }

    openRecords(model, ids) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Dashboard Details",
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", ids]],
            target: "current",
        });
    }

    openRecord(model, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("supplier_ksa.dashboard", SupplierDashboard);
