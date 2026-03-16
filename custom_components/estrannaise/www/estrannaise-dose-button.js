/**
 * Estrannaise HRT Monitor - Dose Logging Button Card
 *
 * Shows a dialog when clicked to select ester/model and dose amount,
 * then calls estrannaise.log_dose service.
 */

const DOSE_BUTTON_VERSION = '3.0.0';

// Friendly ester names keyed by model prefix
const ESTER_NAMES = {
  E: 'Estradiol',
  EB: 'Estradiol Benzoate',
  EV: 'Estradiol Valerate',
  EEn: 'Estradiol Enanthate',
  EC: 'Estradiol Cypionate',
  EUn: 'Estradiol Undecylate',
};

const METHOD_NAMES = {
  im: 'IM',
  subq: 'SubQ',
  patch: 'Patch',
  oral: 'Oral',
};

function friendlyModelName(model) {
  if (!model) return model;
  // "EEn im" → "Estradiol Enanthate (IM)"
  // "E oral" → "Estradiol (Oral)"
  // "patch tw" / "patch ow" → "Estradiol (Patch)"
  if (model.startsWith('patch')) return 'Estradiol (Patch)';
  const parts = model.split(' ');
  const esterKey = parts[0];
  const methodKey = parts[1] || '';
  const esterName = ESTER_NAMES[esterKey] || esterKey;
  const methodName = METHOD_NAMES[methodKey] || methodKey.toUpperCase();
  return `${esterName} (${methodName})`;
}

// Ester+method → PK model key (must stay in sync with const.py ESTER_METHOD_TO_MODEL)
const DOSE_BTN_MODEL_MAP = {
  'EB|im': 'EB im', 'EV|im': 'EV im', 'EEn|im': 'EEn im',
  'EC|im': 'EC im', 'EUn|im': 'EUn im',
  'EB|subq': 'EB im', 'EV|subq': 'EV im', 'EEn|subq': 'EEn im',
  'EC|subq': 'EC im', 'EUn|subq': 'EUn casubq',
  'E|patch': 'patch', 'E|oral': 'E oral',
};

function resolveModelFromConfig(cfg) {
  const key = DOSE_BTN_MODEL_MAP[`${cfg.ester}|${cfg.method}`];
  if (key === 'patch') return (cfg.interval_days || 7) <= 5 ? 'patch tw' : 'patch ow';
  return key || null;
}

if (!customElements.get('estrannaise-dose-button')) {

  class EstrannaiseDoseButton extends HTMLElement {

    static getConfigElement() {
      return document.createElement('estrannaise-dose-button-editor');
    }

    static getStubConfig() {
      return { entity: '', label: 'Log Dose', icon: 'mdi:needle' };
    }

    setConfig(config) {
      if (!config.entity) throw new Error('Please define an entity');
      this.config = {
        label: 'Log Dose',
        icon: 'mdi:needle',
        ...config,
      };
    }

    set hass(hass) {
      this._hass = hass;
      if (!this.shadowRoot) this._buildShadow();
      this._updateState();
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
        .card:active {
          transform: scale(0.97);
        }
        .card.disabled {
          opacity: 0.4;
          pointer-events: none;
        }
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
        .card.confirmed .info { color: rgba(255,255,255,0.8); }

        /* Dialog overlay */
        .overlay {
          display: none;
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          z-index: 999;
          justify-content: center;
          align-items: center;
        }
        .overlay.open { display: flex; }
        .dialog {
          background: var(--ha-card-background, var(--card-background-color, #fff));
          border-radius: 16px;
          padding: 24px;
          min-width: 280px;
          max-width: 360px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .dialog-title {
          font-size: 18px;
          font-weight: 600;
          color: var(--primary-text-color, #212121);
          margin-bottom: 16px;
        }
        .field {
          margin-bottom: 14px;
        }
        .field-label {
          font-size: 13px;
          font-weight: 500;
          color: var(--secondary-text-color, #757575);
          margin-bottom: 4px;
        }
        .field select, .field input {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 15px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          box-sizing: border-box;
          outline: none;
          transition: border-color 0.15s;
        }
        .field select:focus, .field input:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .dialog-buttons {
          display: flex;
          gap: 8px;
          margin-top: 20px;
        }
        .dialog-buttons button {
          flex: 1;
          padding: 10px 16px;
          border: none;
          border-radius: 8px;
          font-size: 15px;
          font-weight: 500;
          cursor: pointer;
          transition: opacity 0.15s;
        }
        .dialog-buttons button:hover { opacity: 0.85; }
        .btn-cancel {
          background: var(--divider-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
        }
        .btn-confirm {
          background: var(--primary-color, #03a9f4);
          color: white;
        }
        .btn-confirm:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
      `;

      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <ha-icon icon="${this.config.icon}"></ha-icon>
        <div class="label">${this._escapeHtml(this.config.label)}</div>
        <div class="info"></div>
      `;
      card.addEventListener('click', () => this._openDialog());

      // Dialog overlay
      const overlay = document.createElement('div');
      overlay.className = 'overlay';
      overlay.innerHTML = `
        <div class="dialog">
          <div class="dialog-title">Log Dose</div>
          <div class="field">
            <div class="field-label">Ester</div>
            <select class="dose-model"></select>
          </div>
          <div class="field">
            <div class="field-label">Dose amount (mg)</div>
            <input type="number" class="dose-amount" min="0.1" max="100" step="0.5">
          </div>
          <div class="dialog-buttons">
            <button class="btn-cancel">Cancel</button>
            <button class="btn-confirm">Log Dose</button>
          </div>
        </div>
      `;

      // Close on overlay background click
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) this._closeDialog();
      });
      overlay.querySelector('.btn-cancel').addEventListener('click', () => this._closeDialog());
      overlay.querySelector('.btn-confirm').addEventListener('click', () => this._confirmDose());

      // Update dose default when model selection changes
      overlay.querySelector('.dose-model').addEventListener('change', (e) => {
        this._onModelChange(e.target.value);
      });

      this.shadowRoot.appendChild(style);
      this.shadowRoot.appendChild(card);
      this.shadowRoot.appendChild(overlay);
    }

    _updateState() {
      if (!this._hass || !this.shadowRoot) return;
      const entity = this._hass.states[this.config.entity];
      if (!entity) return;

      const attrs = entity.attributes || {};
      const mode = attrs.mode || 'manual';
      const card = this.shadowRoot.querySelector('.card');
      const info = this.shadowRoot.querySelector('.info');

      if (mode === 'automatic' && !this.config.force_enable) {
        card.classList.add('disabled');
        if (info) info.textContent = 'Automatic dosing enabled';
      } else {
        card.classList.remove('disabled');
        const doseMg = this.config.dose_mg || attrs.dose_mg || '';
        const model = this.config.model || attrs.model || '';
        if (info) info.textContent = doseMg && model ? `${doseMg}mg ${friendlyModelName(model)}` : '';
      }
    }

    _getAvailableModels() {
      const entity = this._hass && this._hass.states[this.config.entity];
      if (!entity) return [];

      const attrs = entity.attributes || {};
      const allConfigs = attrs.all_configs || [];
      const myUserId = attrs.user_id || 'default';

      // Filter configs to this entity's user_id, then build unique model entries
      const userConfigs = allConfigs.filter(cfg => (cfg.user_id || 'default') === myUserId);
      const configsToUse = userConfigs.length > 0 ? userConfigs : allConfigs;

      const seen = new Set();
      const models = [];
      for (const cfg of configsToUse) {
        const model = resolveModelFromConfig(cfg);
        if (!model || seen.has(model)) continue;
        seen.add(model);
        models.push({
          model,
          dose_mg: cfg.dose_mg,
          label: friendlyModelName(model),
        });
      }

      // If no configs found, fall back to entity's own model
      if (models.length === 0) {
        const model = this.config.model || attrs.model;
        if (model) {
          models.push({
            model,
            dose_mg: this.config.dose_mg || attrs.dose_mg || 4,
            label: friendlyModelName(model),
          });
        }
      }

      return models;
    }

    _openDialog() {
      if (!this._hass || this._busy) return;
      const entity = this._hass.states[this.config.entity];
      if (!entity) return;

      const attrs = entity.attributes || {};
      const mode = attrs.mode || 'manual';
      if (mode === 'automatic' && !this.config.force_enable) return;

      const models = this._getAvailableModels();
      const select = this.shadowRoot.querySelector('.dose-model');
      const input = this.shadowRoot.querySelector('.dose-amount');

      // Show user_id in dialog title when multi-user
      const dialogTitle = this.shadowRoot.querySelector('.dialog-title');
      const users = attrs.users || {};
      const myUserId = attrs.user_id || 'default';
      if (dialogTitle) {
        dialogTitle.textContent = Object.keys(users).length > 1
          ? `Log Dose (${myUserId})`
          : 'Log Dose';
      }

      // Populate model dropdown
      select.innerHTML = '';
      const currentModel = this.config.model || attrs.model || '';
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.model;
        opt.textContent = m.label;
        if (m.model === currentModel) opt.selected = true;
        select.appendChild(opt);
      }

      // Set default dose from selected model's config or card config
      const selectedModel = models.find(m => m.model === select.value) || models[0];
      input.value = this.config.dose_mg || (selectedModel && selectedModel.dose_mg) || attrs.dose_mg || 4;

      // Update dose unit label for patches
      const doseLabel = this.shadowRoot.querySelector('.dose-amount').closest('.field').querySelector('.field-label');
      if (select.value && select.value.startsWith('patch')) {
        doseLabel.textContent = 'Dose amount (mcg/day)';
      } else {
        doseLabel.textContent = 'Dose amount (mg)';
      }

      this.shadowRoot.querySelector('.overlay').classList.add('open');
    }

    _onModelChange(modelValue) {
      const entity = this._hass && this._hass.states[this.config.entity];
      if (!entity) return;

      const attrs = entity.attributes || {};
      const allConfigs = attrs.all_configs || [];
      const input = this.shadowRoot.querySelector('.dose-amount');

      // Update dose default to match selected model's configured dose
      const cfg = allConfigs.find(c => resolveModelFromConfig(c) === modelValue);
      if (cfg) {
        input.value = cfg.dose_mg;
      }

      // Update unit label
      const doseLabel = input.closest('.field').querySelector('.field-label');
      if (modelValue && modelValue.startsWith('patch')) {
        doseLabel.textContent = 'Dose amount (mcg/day)';
      } else {
        doseLabel.textContent = 'Dose amount (mg)';
      }
    }

    _closeDialog() {
      this.shadowRoot.querySelector('.overlay').classList.remove('open');
    }

    async _confirmDose() {
      if (this._busy) return;

      const select = this.shadowRoot.querySelector('.dose-model');
      const input = this.shadowRoot.querySelector('.dose-amount');
      const model = select.value;
      const doseMg = parseFloat(input.value);

      if (!model || !doseMg || doseMg <= 0) return;

      this._busy = true;
      const confirmBtn = this.shadowRoot.querySelector('.btn-confirm');
      confirmBtn.disabled = true;

      try {
        await this._hass.callService('estrannaise', 'log_dose', {
          entity_id: this.config.entity,
          model: model,
          dose_mg: doseMg,
        });

        this._closeDialog();

        // Visual confirmation on the card
        const card = this.shadowRoot.querySelector('.card');
        const label = this.shadowRoot.querySelector('.label');
        const prevLabel = label.textContent;
        card.classList.add('confirmed');
        label.textContent = 'Dose logged!';

        const info = this.shadowRoot.querySelector('.info');
        const prevInfo = info.textContent;
        info.textContent = `${doseMg}mg ${friendlyModelName(model)}`;

        setTimeout(() => {
          card.classList.remove('confirmed');
          label.textContent = prevLabel;
          info.textContent = prevInfo;
          this._busy = false;
        }, 2000);
      } catch (err) {
        console.error('Failed to log dose:', err);
        confirmBtn.disabled = false;
        this._busy = false;

        const label = this.shadowRoot.querySelector('.label');
        const prevLabel = label.textContent;
        label.textContent = 'Error!';
        setTimeout(() => { label.textContent = prevLabel; }, 2000);
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

  customElements.define('estrannaise-dose-button', EstrannaiseDoseButton);
}

// ── Editor ──────────────────────────────────────────────────────────────────

if (!customElements.get('estrannaise-dose-button-editor')) {

  class EstrannaiseDoseButtonEditor extends HTMLElement {

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
        model: this.config.model || 'auto',
        dose_mg: this.config.dose_mg || '',
        label: this.config.label || 'Log Dose',
        icon: this.config.icon || 'mdi:needle',
      };
    }

    _buildForm() {
      if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '';

      const form = document.createElement('ha-form');
      form.hass = this._hass;
      form.schema = [
        { name: 'entity', selector: { entity: { domain: 'sensor' } } },
        {
          name: 'model',
          label: 'Default ester (pre-selected in dialog)',
          selector: { select: {
            options: [
              { value: 'auto', label: 'Auto (from entity)' },
              { value: 'EB im', label: 'Estradiol Benzoate (IM)' },
              { value: 'EV im', label: 'Estradiol Valerate (IM)' },
              { value: 'EEn im', label: 'Estradiol Enanthate (IM)' },
              { value: 'EC im', label: 'Estradiol Cypionate (IM)' },
              { value: 'EUn im', label: 'Estradiol Undecylate (IM)' },
              { value: 'EUn casubq', label: 'Estradiol Undecylate (SubQ)' },
              { value: 'E oral', label: 'Estradiol (Oral)' },
              { value: 'patch', label: 'Estradiol (Patch)' },
            ],
            mode: 'dropdown',
          }},
        },
        { name: 'dose_mg', label: 'Default dose (mg)', selector: { number: { min: 0, max: 100, step: 'any', mode: 'box' } } },
        { name: 'label', label: 'Button label', selector: { text: {} } },
        { name: 'icon', label: 'Icon', selector: { icon: {} } },
      ];
      form.data = this._getFormData();
      form.computeLabel = (schema) => {
        const labels = {
          entity: 'Entity',
          model: 'Default ester',
          dose_mg: 'Default dose (mg)',
          label: 'Button label',
          icon: 'Icon',
        };
        return labels[schema.name] || schema.name;
      };
      form.addEventListener('value-changed', (ev) => {
        const newData = ev.detail.value;
        this.config = { ...this.config, ...newData };
        // Remove 'auto' / empty optional fields so they fall back to entity defaults
        if (!this.config.model || this.config.model === 'auto') delete this.config.model;
        if (!this.config.dose_mg) delete this.config.dose_mg;
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

  customElements.define('estrannaise-dose-button-editor', EstrannaiseDoseButtonEditor);
}

// ── Register ────────────────────────────────────────────────────────────────

if (!window.customCards) window.customCards = [];
if (!window.customCards.some(c => c.type === 'estrannaise-dose-button')) {
  window.customCards.push({
    type: 'estrannaise-dose-button',
    name: 'Estrannaise Dose Button',
    description: 'Button to log an estrogen dose',
  });
}
