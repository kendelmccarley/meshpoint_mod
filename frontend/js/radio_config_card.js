/**
 * Radio tab — Radio Configuration card.
 *
 * Two stacked panes:
 *   - PRESET: region + Meshtastic preset selector. Choosing a preset
 *     auto-fills the SF/BW/CR readouts. The wider region selector
 *     also auto-fills the frequency input.
 *   - TUNING: explicit frequency, TX power, hop limit. Power/hop
 *     apply at runtime; freq/preset/region require a service restart.
 * A horizontal readout strip shows the computed sync word, preamble,
 * and effective SF/BW/CR for the current selection.
 */
class RadioConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._presets = [];
        this._regions = [];
        this._currentRadio = null;
        this._currentTx = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Radio Configuration</h3>
                <span class="r-card__subtitle" id="r-config-subtitle">--</span>
            </div>
            <div class="config-stack">
                <div class="config-pane">
                    <div class="config-pane__label">Preset</div>
                    <div class="config-pane__inputs">
                        <div class="r-field">
                            <label class="r-field__label" for="r-region">Region</label>
                            <select class="r-select" id="r-region"></select>
                        </div>
                        <div class="r-field">
                            <label class="r-field__label" for="r-preset">Modem preset</label>
                            <select class="r-select" id="r-preset"></select>
                        </div>
                    </div>
                </div>
                <div class="config-pane">
                    <div class="config-pane__label">Tuning</div>
                    <div class="config-pane__inputs">
                        <div class="r-field">
                            <label class="r-field__label" for="r-freq">Frequency (MHz)</label>
                            <input type="number" class="r-input r-input--mono r-input--narrow"
                                   id="r-freq" step="0.001" min="100" max="1000" />
                        </div>
                        <div class="r-field">
                            <label class="r-field__label" for="r-tx-power">TX power (dBm)</label>
                            <input type="number" class="r-input r-input--mono r-input--narrow"
                                   id="r-tx-power" min="0" max="30" />
                        </div>
                        <div class="r-field">
                            <label class="r-field__label" for="r-hop-limit">Hop limit</label>
                            <input type="number" class="r-input r-input--mono r-input--narrow"
                                   id="r-hop-limit" min="0" max="7" />
                        </div>
                    </div>
                </div>
            </div>
            <div class="readout-strip">
                <div class="readout-strip__label">Computed</div>
                <div class="r-readout">
                    <span class="r-readout__label">SF</span>
                    <span class="r-readout__value" id="r-sf">--</span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">BW</span>
                    <span class="r-readout__value" id="r-bw">--</span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">CR</span>
                    <span class="r-readout__value" id="r-cr">--</span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">Sync</span>
                    <span class="r-readout__value" id="r-sync">--</span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">Preamble</span>
                    <span class="r-readout__value" id="r-preamble">--</span>
                </div>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--primary"
                        id="r-save-config">Save Radio Settings</button>
            </div>
        `;
    }

    render(config) {
        this._presets = config.presets || [];
        this._regions = config.regions || [];
        this._currentRadio = config.radio || {};
        this._currentTx = config.transmit || {};

        this._renderRegionOptions();
        this._renderPresetOptions();
        this._renderInputs();
        this._renderReadouts(this._currentRadio);
        this._renderSubtitle(this._currentRadio);
        this._wire();
    }

    _renderRegionOptions() {
        const sel = this._root.querySelector('#r-region');
        sel.innerHTML = this._regions.map((r) => {
            const selected = r.id === this._currentRadio.region ? 'selected' : '';
            return `<option value="${r.id}" ${selected}>`
                + `${this._api.escape(r.name)} (${r.frequency_mhz} MHz)`
                + `</option>`;
        }).join('');
    }

    _renderPresetOptions() {
        const sel = this._root.querySelector('#r-preset');
        const opts = this._presets.map((p) => {
            const selected = p.name === this._currentRadio.current_preset ? 'selected' : '';
            const rxOnly = p.tx_capable ? '' : ' (RX only)';
            return `<option value="${p.name}" ${selected}>`
                + `${this._api.escape(p.display_name)}${rxOnly}</option>`;
        });
        const customSelected = !this._currentRadio.current_preset ? 'selected' : '';
        opts.push(`<option value="CUSTOM" ${customSelected}>Custom</option>`);
        sel.innerHTML = opts.join('');
    }

    _renderInputs() {
        this._root.querySelector('#r-freq').value = this._currentRadio.frequency_mhz || '';
        this._root.querySelector('#r-tx-power').value = this._currentTx.tx_power_dbm || '';
        this._root.querySelector('#r-hop-limit').value = this._currentTx.hop_limit || '';
    }

    _renderReadouts(radio) {
        this._root.querySelector('#r-sf').textContent =
            radio.spreading_factor ? `SF${radio.spreading_factor}` : '--';
        this._root.querySelector('#r-bw').textContent =
            radio.bandwidth_khz ? `${radio.bandwidth_khz} kHz` : '--';
        this._root.querySelector('#r-cr').textContent = radio.coding_rate || '--';
        this._root.querySelector('#r-sync').textContent = radio.sync_word || '--';
        this._root.querySelector('#r-preamble').textContent =
            radio.preamble_length ? `${radio.preamble_length} sym` : '--';
    }

    _renderSubtitle(radio) {
        const sub = this._root.querySelector('#r-config-subtitle');
        const preset = radio.current_preset || 'Custom';
        const freq = radio.frequency_mhz ? `${radio.frequency_mhz} MHz` : '';
        sub.textContent = freq ? `${preset} -- ${freq}` : preset;
    }

    _wire() {
        const presetSel = this._root.querySelector('#r-preset');
        presetSel.onchange = () => {
            const name = presetSel.value;
            if (name === 'CUSTOM') return;
            const p = this._presets.find((x) => x.name === name);
            if (!p) return;
            this._renderReadouts({
                spreading_factor: p.sf,
                bandwidth_khz: p.bw_khz,
                coding_rate: p.cr,
                sync_word: this._currentRadio.sync_word,
                preamble_length: this._currentRadio.preamble_length,
            });
        };

        const regionSel = this._root.querySelector('#r-region');
        regionSel.onchange = () => {
            const r = this._regions.find((x) => x.id === regionSel.value);
            if (r) this._root.querySelector('#r-freq').value = r.frequency_mhz;
        };

        this._root.querySelector('#r-save-config').onclick = () => this._save();
    }

    async _save() {
        const radio = this._currentRadio;
        const tx = this._currentTx;
        const radioPayload = {};
        const txPayload = {};

        const region = this._root.querySelector('#r-region').value;
        if (region !== radio.region) radioPayload.region = region;

        const preset = this._root.querySelector('#r-preset').value;
        if (preset !== 'CUSTOM' && preset !== radio.current_preset) {
            radioPayload.preset = preset;
        }

        const freq = parseFloat(this._root.querySelector('#r-freq').value);
        if (!isNaN(freq) && freq !== radio.frequency_mhz) {
            radioPayload.frequency_mhz = freq;
        }

        const txPower = parseInt(this._root.querySelector('#r-tx-power').value, 10);
        if (!isNaN(txPower) && txPower !== tx.tx_power_dbm) {
            txPayload.tx_power_dbm = txPower;
        }

        const hopLimit = parseInt(this._root.querySelector('#r-hop-limit').value, 10);
        if (!isNaN(hopLimit) && hopLimit !== tx.hop_limit) {
            txPayload.hop_limit = hopLimit;
        }

        let restartNeeded = false;
        if (Object.keys(radioPayload).length > 0) {
            const result = await this._api.put('/api/config/radio', radioPayload);
            if (result && result.restart_required) restartNeeded = true;
        }
        if (Object.keys(txPayload).length > 0) {
            await this._api.put('/api/config/transmit', txPayload);
        }

        this._api.toast('Radio settings saved');
        if (restartNeeded) {
            this._api.signalRestart(
                'Radio changes take effect on next service restart.',
            );
        }
        await this._api.refresh();
    }
}

window.RadioConfigCard = RadioConfigCard;
