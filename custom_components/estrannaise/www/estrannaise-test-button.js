/**
 * Estrannaise HRT Monitor - Blood Test Input Button Card
 *
 * A button that opens a dialog for entering blood estradiol test results.
 */

const TEST_BUTTON_VERSION = '2.0.0';

if (!customElements.get('estrannaise-test-button')) {

  class EstrannaisTestButton extends HTMLElement {

    static getConfigElement() {
      return document.createElement('estrannaise-test-button-editor');
    }

    static getStubConfig() {
      return { entity: '', label: 'Log Blood Test', icon: 'mdi:test-tube' };
    }

    setConfig(config) {
      if (!config.entity) throw new Error('Please define an entity');
      this.config = {
        label: 'Log Blood Test',
        icon: 'mdi:test-tube',
        ...config,
      };
    }

    set hass(hass) {
      this._hass = hass;
      if (!this.shadowRoot) this._buildShadow();
    }

    _buildShadow() {
      this.attachShadow({ mode: 'open' });

      const style = document.createElement('style');
      style.textContent = `
        :host { display: block; }
        .card {
          background: var(--ha-card-background, var(--card-background-color, #fff));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
          padding: 16px;
          text-align: center;
          cursor: pointer;
          transition: transform 0.1s, box-shadow 0.15s;
          user-select: none;
        }
        .card:hover {
          box-shadow: var(--ha-card-box-shadow, 0 4px 12px rgba(0,0,0,0.15));
        }
        .card:active { transform: scale(0.97); }
        .card.confirmed {
          background: var(--success-color, #4CAF50);
          color: white;
        }
        ha-icon {
          --mdc-icon-size: 36px;
          color: var(--primary-color);
          display: block;
          margin: 0 auto 8px;
        }
        .card.confirmed ha-icon { color: white; }
        .label {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .card.confirmed .label { color: white; }
        .info {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
          margin-top: 4px;
        }

        /* Dialog overlay */
        .dialog-overlay {
          display: none;
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          z-index: 9999;
          justify-content: center;
          align-items: center;
        }
        .dialog-overlay.open { display: flex; }
        .dialog {
          background: var(--ha-card-background, var(--card-background-color, #fff));
          border-radius: 16px;
          padding: 24px;
          min-width: 320px;
          max-width: 400px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .dialog h3 {
          margin: 0 0 16px;
          font-size: 18px;
          color: var(--primary-text-color, #212121);
        }
        .dialog label {
          display: block;
          margin-top: 12px;
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .dialog input, .dialog textarea {
          width: 100%;
          padding: 10px;
          margin-top: 4px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 8px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          font-size: 14px;
          box-sizing: border-box;
        }
        .dialog textarea {
          resize: vertical;
          min-height: 60px;
        }
        .dialog .buttons {
          display: flex;
          gap: 8px;
          margin-top: 20px;
          justify-content: flex-end;
        }
        .dialog button {
          padding: 10px 20px;
          border: none;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: opacity 0.15s;
        }
        .dialog button:hover { opacity: 0.85; }
        .dialog .btn-cancel {
          background: var(--secondary-background-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
        }
        .dialog .btn-submit {
          background: var(--primary-color, #03A9F4);
          color: white;
        }
        .dialog .btn-submit:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .dialog .error {
          color: var(--error-color, #F44336);
          font-size: 13px;
          margin-top: 8px;
        }
      `;

      const wrapper = document.createElement('div');

      // Main button
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <ha-icon icon="${this.config.icon}"></ha-icon>
        <div class="label">${this._escapeHtml(this.config.label)}</div>
        <div class="info">Record blood test results</div>
      `;
      card.addEventListener('click', () => this._openDialog());

      // Dialog
      const overlay = document.createElement('div');
      overlay.className = 'dialog-overlay';
      overlay.innerHTML = `
        <div class="dialog">
          <h3>Log Blood Test</h3>

          <label>Date & Time</label>
          <input type="datetime-local" id="test-datetime" />

          <label>Estradiol Level (<span class="unit-label">pg/mL</span>)</label>
          <input type="number" id="test-level" min="0" max="5000" step="0.1" placeholder="e.g. 150" />

          <label>Notes (optional)</label>
          <textarea id="test-notes" placeholder="Lab name, fasting status, etc."></textarea>

          <div id="schedule-toggle-section" style="display:none; margin-top: 12px;">
            <div style="font-size: 13px; color: var(--warning-color, #FF9800); margin-bottom: 8px;">
              This test is from before your earliest recorded dose.
            </div>
            <label style="display: flex; align-items: center; gap: 8px; margin: 0; cursor: pointer;">
              <input type="checkbox" id="test-on-schedule" checked style="width: 16px; height: 16px;" />
              <span style="font-size: 13px;">I was on this dosing schedule at test time</span>
            </label>
          </div>

          <div class="error" id="test-error"></div>

          <div class="buttons">
            <button class="btn-cancel" id="test-cancel">Cancel</button>
            <button class="btn-submit" id="test-submit">Submit</button>
          </div>
        </div>
      `;

      // Close on overlay click (outside dialog)
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) this._closeDialog();
      });

      wrapper.appendChild(card);
      wrapper.appendChild(overlay);

      this.shadowRoot.appendChild(style);
      this.shadowRoot.appendChild(wrapper);

      // Bind dialog buttons
      this.shadowRoot.getElementById('test-cancel').addEventListener('click', () => this._closeDialog());
      this.shadowRoot.getElementById('test-submit').addEventListener('click', () => this._submitTest());
      this.shadowRoot.getElementById('test-datetime').addEventListener('input', () => this._updateScheduleToggle());
    }

    _openDialog() {
      const overlay = this.shadowRoot.querySelector('.dialog-overlay');
      overlay.classList.add('open');

      // Pre-fill datetime with current local time and block future dates
      const now = new Date();
      const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
      const dtInput = this.shadowRoot.getElementById('test-datetime');
      dtInput.value = local.toISOString().slice(0, 16);
      dtInput.max = local.toISOString().slice(0, 16);
      this.shadowRoot.getElementById('test-level').value = '';
      this.shadowRoot.getElementById('test-notes').value = '';
      this.shadowRoot.getElementById('test-error').textContent = '';
      this.shadowRoot.getElementById('schedule-toggle-section').style.display = 'none';
      this.shadowRoot.getElementById('test-on-schedule').checked = true;

      // Update unit label and show user_id when multi-user
      if (this._hass) {
        const entity = this._hass.states[this.config.entity];
        if (entity) {
          const attrs = entity.attributes || {};
          const units = attrs.units || 'pg/mL';
          const unitLabel = this.shadowRoot.querySelector('.unit-label');
          if (unitLabel) unitLabel.textContent = units;

          const dialogH3 = this.shadowRoot.querySelector('.dialog h3');
          const users = attrs.users || {};
          const myUserId = attrs.user_id || 'default';
          if (dialogH3) {
            dialogH3.textContent = Object.keys(users).length > 1
              ? `Log Blood Test (${myUserId})`
              : 'Log Blood Test';
          }
        }
      }

      // Focus the level input
      setTimeout(() => {
        this.shadowRoot.getElementById('test-level').focus();
      }, 100);
    }

    _closeDialog() {
      const overlay = this.shadowRoot.querySelector('.dialog-overlay');
      overlay.classList.remove('open');
    }

    _updateScheduleToggle() {
      const section = this.shadowRoot.getElementById('schedule-toggle-section');
      const dtInput = this.shadowRoot.getElementById('test-datetime');
      if (!dtInput.value || !this._hass) { section.style.display = 'none'; return; }

      const timestamp = new Date(dtInput.value).getTime() / 1000;
      const entity = this._hass.states[this.config.entity];
      if (!entity) { section.style.display = 'none'; return; }

      const doses = entity.attributes?.doses || [];
      if (doses.length === 0) {
        // No doses at all — always show the toggle
        section.style.display = '';
        return;
      }

      const earliestDose = Math.min(...doses.map(d => d.timestamp));
      section.style.display = (timestamp < earliestDose) ? '' : 'none';
    }

    async _submitTest() {
      const datetimeInput = this.shadowRoot.getElementById('test-datetime');
      const levelInput = this.shadowRoot.getElementById('test-level');
      const notesInput = this.shadowRoot.getElementById('test-notes');
      const errorEl = this.shadowRoot.getElementById('test-error');

      const level = parseFloat(levelInput.value);
      if (isNaN(level) || level < 0) {
        errorEl.textContent = 'Please enter a valid estradiol level.';
        return;
      }

      const datetime = datetimeInput.value;
      if (!datetime) {
        errorEl.textContent = 'Please select a date and time.';
        return;
      }

      // Convert to unix timestamp
      const timestamp = new Date(datetime).getTime() / 1000;

      // Block future dates
      if (timestamp > Date.now() / 1000 + 60) {
        errorEl.textContent = 'Blood test date cannot be in the future.';
        return;
      }

      // If units are pmol/L, convert back to pg/mL for storage
      let levelPgMl = level;
      if (this._hass) {
        const entity = this._hass.states[this.config.entity];
        if (entity && entity.attributes?.units === 'pmol/L') {
          levelPgMl = level / 3.6713;
        }
      }

      const submitBtn = this.shadowRoot.getElementById('test-submit');
      submitBtn.disabled = true;
      errorEl.textContent = '';

      try {
        const serviceData = {
          entity_id: this.config.entity,
          level_pg_ml: levelPgMl,
          timestamp: timestamp,
          notes: notesInput.value || undefined,
        };
        // Include on_schedule only when the toggle was shown
        const scheduleSection = this.shadowRoot.getElementById('schedule-toggle-section');
        if (scheduleSection.style.display !== 'none') {
          serviceData.on_schedule = this.shadowRoot.getElementById('test-on-schedule').checked;
        }
        await this._hass.callService('estrannaise', 'log_blood_test', serviceData);

        this._closeDialog();

        // Visual confirmation on the button
        const card = this.shadowRoot.querySelector('.card');
        const label = this.shadowRoot.querySelector('.label');
        const prevLabel = label.textContent;
        card.classList.add('confirmed');
        label.textContent = 'Test logged!';
        setTimeout(() => {
          card.classList.remove('confirmed');
          label.textContent = prevLabel;
        }, 2000);
      } catch (err) {
        console.error('Failed to log blood test:', err);
        errorEl.textContent = 'Failed to submit. Check logs for details.';
      } finally {
        submitBtn.disabled = false;
      }
    }

    _escapeHtml(text) {
      const el = document.createElement('span');
      el.textContent = text;
      return el.innerHTML;
    }

    getCardSize() {
      return 2;
    }
  }

  customElements.define('estrannaise-test-button', EstrannaisTestButton);
}

// ── Editor ──────────────────────────────────────────────────────────────────

if (!customElements.get('estrannaise-test-button-editor')) {

  class EstrannaisTestButtonEditor extends HTMLElement {

    setConfig(config) {
      this.config = { ...config };
      if (this._ignoreNextConfig) {
        this._ignoreNextConfig = false;
        return;
      }
      if (!this._form) {
        this._buildForm();
      } else {
        this._form.data = this._getFormData();
      }
    }

    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
    }

    _getFormData() {
      return {
        entity: this.config.entity || '',
        label: this.config.label || 'Log Blood Test',
        icon: this.config.icon || 'mdi:test-tube',
      };
    }

    _buildForm() {
      if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '';

      const form = document.createElement('ha-form');
      form.hass = this._hass;
      form.schema = [
        { name: 'entity', selector: { entity: { domain: 'sensor' } } },
        { name: 'label', label: 'Button label', selector: { text: {} } },
        { name: 'icon', label: 'Icon', selector: { icon: {} } },
      ];
      form.data = this._getFormData();
      form.computeLabel = (schema) => {
        const labels = {
          entity: 'Entity',
          label: 'Button label',
          icon: 'Icon',
        };
        return labels[schema.name] || schema.name;
      };
      form.addEventListener('value-changed', (ev) => {
        const newData = ev.detail.value;
        this.config = { ...this.config, ...newData };
        this._ignoreNextConfig = true;
        this.dispatchEvent(new CustomEvent('config-changed', {
          bubbles: true, composed: true,
          detail: { config: this.config },
        }));
      });

      this._form = form;
      this.shadowRoot.appendChild(form);
    }
  }

  customElements.define('estrannaise-test-button-editor', EstrannaisTestButtonEditor);
}

// ── Register ────────────────────────────────────────────────────────────────

if (!window.customCards) window.customCards = [];
if (!window.customCards.some(c => c.type === 'estrannaise-test-button')) {
  window.customCards.push({
    type: 'estrannaise-test-button',
    name: 'Estrannaise Blood Test Button',
    description: 'Button to log blood estradiol test results',
  });
}
