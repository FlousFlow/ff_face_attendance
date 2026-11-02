/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

class FaceDeviceCredential extends Component {
    static props = { ...standardActionServiceProps };
    static template = xml`
        <div class="o_action_manager d-flex justify-content-center align-items-center p-4">
            <main class="card p-4" style="max-width: 720px">
                <h2>Copy kiosk credential</h2>
                <p>This value is shown once. Store it in the kiosk's protected local configuration.</p>
                <input class="form-control font-monospace" readonly="readonly" t-att-value="credential"/>
                <button class="btn btn-primary mt-3" t-on-click="copy">Copy credential</button>
                <p class="mt-3 text-warning">If you leave this screen without copying it, rotate the credential again.</p>
            </main>
        </div>`;

    setup() {
        this.credential = this.props.action.params.credential;
    }

    async copy() {
        await navigator.clipboard.writeText(this.credential);
    }
}

registry.category("actions").add("ff_face_device_credential", FaceDeviceCredential);
