/**
 * Bitaxe Monitor - Miner Control Modal
 */

let selectedMiner = null;
let controlLimits = {
    min_frequency: 400, max_frequency: 1000,
    min_voltage: 1000, max_voltage: 1400,
    min_fan_speed: 0, max_fan_speed: 100
};
let fanMode = 'auto';

// =================================================================
// Initialization
// =================================================================

function initControls() {
    // Fetch control limits on load
    fetch('/api/control/limits')
        .then(r => r.json())
        .then(limits => {
            controlLimits = limits;
            // Frequency
            document.getElementById('freqSlider').min = limits.min_frequency;
            document.getElementById('freqSlider').max = limits.max_frequency;
            document.getElementById('freqInput').min = limits.min_frequency;
            document.getElementById('freqInput').max = limits.max_frequency;
            // Voltage
            document.getElementById('voltageSlider').min = limits.min_voltage;
            document.getElementById('voltageSlider').max = limits.max_voltage;
            document.getElementById('voltageInput').min = limits.min_voltage;
            document.getElementById('voltageInput').max = limits.max_voltage;
            // Fan
            document.getElementById('fanSlider').min = limits.min_fan_speed;
            document.getElementById('fanSlider').max = limits.max_fan_speed;
            document.getElementById('fanInput').min = limits.min_fan_speed;
            document.getElementById('fanInput').max = limits.max_fan_speed;
        })
        .catch(() => {});

    // Set up slider/input sync
    syncControls('freqSlider', 'freqInput');
    syncControls('voltageSlider', 'voltageInput');
    syncControls('fanSlider', 'fanInput');

    // Close modal on overlay click
    document.getElementById('controlModal').addEventListener('click', function(e) {
        if (e.target === this) closeModal();
    });

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });
}

// Sync sliders with number inputs
function syncControls(sliderId, inputId) {
    const slider = document.getElementById(sliderId);
    const input = document.getElementById(inputId);

    slider.addEventListener('input', () => { input.value = slider.value; });
    input.addEventListener('input', () => {
        let val = parseInt(input.value) || parseInt(slider.min);
        val = Math.max(parseInt(slider.min), Math.min(parseInt(slider.max), val));
        slider.value = val;
    });
    input.addEventListener('blur', () => {
        let val = parseInt(input.value) || parseInt(slider.min);
        val = Math.max(parseInt(slider.min), Math.min(parseInt(slider.max), val));
        input.value = val;
        slider.value = val;
    });
}

// =================================================================
// Modal Open/Close
// =================================================================

async function openControlModal(miner) {
    selectedMiner = miner;
    document.getElementById('modalTitle').textContent = miner.name + ' Settings';

    // Show modal with loading state
    document.getElementById('statusMessage').className = 'status-message';
    document.getElementById('controlModal').classList.add('active');

    // Use cached values initially
    setControlValues(miner.frequency, miner.core_voltage, miner.fan_speed, true);

    // Fetch live settings from device
    try {
        const response = await fetch(`/api/control/${miner.name}/settings`);
        if (response.ok) {
            const settings = await response.json();
            setControlValues(settings.frequency, settings.core_voltage, settings.fan_speed, settings.autofan);
        }
    } catch (e) {
        console.error('Failed to fetch live settings:', e);
    }
}

function setControlValues(frequency, voltage, fanSpeed, autofan) {
    // Current settings display
    document.getElementById('currentFreq').textContent = frequency + ' MHz';
    document.getElementById('currentVoltage').textContent = voltage + ' mV';
    document.getElementById('currentFan').textContent = autofan ? 'Auto' : fanSpeed + '%';

    // Set control values
    document.getElementById('freqSlider').value = frequency;
    document.getElementById('freqInput').value = frequency;
    document.getElementById('voltageSlider').value = voltage;
    document.getElementById('voltageInput').value = voltage;
    document.getElementById('fanSlider').value = fanSpeed;
    document.getElementById('fanInput').value = fanSpeed;

    // Set fan mode based on device state
    setFanMode(autofan ? 'auto' : 'manual');
}

function closeModal() {
    document.getElementById('controlModal').classList.remove('active');
    selectedMiner = null;
}

// =================================================================
// Fan Mode Toggle
// =================================================================

function setFanMode(mode) {
    fanMode = mode;
    const autoBtn = document.getElementById('fanAutoBtn');
    const manualBtn = document.getElementById('fanManualBtn');
    const slider = document.getElementById('fanSlider');
    const input = document.getElementById('fanInput');

    if (mode === 'auto') {
        autoBtn.classList.add('active');
        manualBtn.classList.remove('active');
        slider.disabled = true;
        input.disabled = true;
    } else {
        autoBtn.classList.remove('active');
        manualBtn.classList.add('active');
        slider.disabled = false;
        input.disabled = false;
    }
}

// =================================================================
// Status Messages
// =================================================================

function showStatus(message, isError = false) {
    const el = document.getElementById('statusMessage');
    el.textContent = message;
    el.className = 'status-message ' + (isError ? 'error' : 'success');
    setTimeout(() => {
        el.className = 'status-message';
    }, 3000);
}

// =================================================================
// Apply Settings
// =================================================================

async function applyFrequency() {
    if (!selectedMiner) return;
    const frequency = parseInt(document.getElementById('freqInput').value);

    if (frequency < controlLimits.min_frequency || frequency > controlLimits.max_frequency) {
        showStatus(`Frequency must be ${controlLimits.min_frequency}-${controlLimits.max_frequency} MHz`, true);
        return;
    }

    try {
        const response = await fetch(`/api/control/${selectedMiner.name}/frequency`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frequency })
        });
        const data = await response.json();
        if (response.ok) {
            showStatus(`Frequency set to ${frequency} MHz`);
            document.getElementById('currentFreq').textContent = frequency + ' MHz';
        } else {
            showStatus(data.error || 'Failed to set frequency', true);
        }
    } catch (e) {
        showStatus('Connection error', true);
    }
}

async function applyVoltage() {
    if (!selectedMiner) return;
    const voltage = parseInt(document.getElementById('voltageInput').value);

    if (voltage < controlLimits.min_voltage || voltage > controlLimits.max_voltage) {
        showStatus(`Voltage must be ${controlLimits.min_voltage}-${controlLimits.max_voltage} mV`, true);
        return;
    }

    try {
        const response = await fetch(`/api/control/${selectedMiner.name}/voltage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voltage })
        });
        const data = await response.json();
        if (response.ok) {
            showStatus(`Voltage set to ${voltage} mV`);
            document.getElementById('currentVoltage').textContent = voltage + ' mV';
        } else {
            showStatus(data.error || 'Failed to set voltage', true);
        }
    } catch (e) {
        showStatus('Connection error', true);
    }
}

async function applyFan() {
    if (!selectedMiner) return;

    if (fanMode === 'auto') {
        try {
            const response = await fetch(`/api/control/${selectedMiner.name}/autofan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (response.ok) {
                showStatus('Auto fan enabled');
                document.getElementById('currentFan').textContent = 'Auto';
            } else {
                showStatus(data.error || 'Failed to enable auto fan', true);
            }
        } catch (e) {
            showStatus('Connection error', true);
        }
    } else {
        const fan_speed = parseInt(document.getElementById('fanInput').value);

        if (fan_speed < controlLimits.min_fan_speed || fan_speed > controlLimits.max_fan_speed) {
            showStatus(`Fan speed must be ${controlLimits.min_fan_speed}-${controlLimits.max_fan_speed}%`, true);
            return;
        }

        try {
            const response = await fetch(`/api/control/${selectedMiner.name}/fan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fan_speed })
            });
            const data = await response.json();
            if (response.ok) {
                showStatus(`Fan speed set to ${fan_speed}%`);
                document.getElementById('currentFan').textContent = fan_speed + '%';
            } else {
                showStatus(data.error || 'Failed to set fan speed', true);
            }
        } catch (e) {
            showStatus('Connection error', true);
        }
    }
}

async function restartMiner() {
    if (!selectedMiner) return;
    if (!confirm(`Are you sure you want to restart ${selectedMiner.name}?`)) return;

    try {
        const response = await fetch(`/api/control/${selectedMiner.name}/restart`, {
            method: 'POST'
        });
        const data = await response.json();
        if (response.ok) {
            showStatus('Restart command sent');
            setTimeout(closeModal, 1500);
        } else {
            showStatus(data.error || 'Failed to restart', true);
        }
    } catch (e) {
        showStatus('Connection error', true);
    }
}

// Initialize controls when DOM is ready
document.addEventListener('DOMContentLoaded', initControls);
