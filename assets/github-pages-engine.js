/**
 * The Bengaluru Clinic - Client-Side Mock & Simulation Engine for GitHub Pages
 * ----------------------------------------------------------------------------
 * Allows the entire application (Patient Simulator, Scenario Engine, Doctor Picker,
 * and Read-Only Staff Cockpit) to run 100% inside the browser on GitHub Pages
 * without requiring any backend server or external cloud service.
 */

(function () {
  const isGitHubPages = window.location.hostname.endsWith('github.io') ||
                        window.location.protocol === 'file:' ||
                        window.__FORCE_CLIENT_MOCK__ === true;

  console.log('[Clinic Engine] Zero-Server Engine: ' + (isGitHubPages ? 'ACTIVE (GitHub Pages)' : 'HYBRID (Fallback)'));

  // In-Memory Simulation State
  const CLINICIANS_DATA = [
  {
    "clinician_id": "DOC-101",
    "display_name": "Dr. Ananya Varma",
    "service_label": "Sexual & Relationship Therapy",
    "specialty": "Sexology & Mental Health",
    "duration_minutes": 50,
    "fee": 2500.0,
    "slots": [
      {
        "slot_id": "SLOT-101",
        "start_iso": "2026-11-03T10:00:00",
        "end_iso": "2026-11-03T10:50:00",
        "label": "Tomorrow, 10:00 AM"
      },
      {
        "slot_id": "SLOT-A2",
        "start_iso": "2026-11-03T11:30:00",
        "end_iso": "2026-11-03T12:20:00",
        "label": "Tomorrow, 11:30 AM"
      },
      {
        "slot_id": "SLOT-103",
        "start_iso": "2026-11-03T15:00:00",
        "end_iso": "2026-11-03T15:50:00",
        "label": "Tomorrow, 3:00 PM"
      },
      {
        "slot_id": "SLOT-A3",
        "start_iso": "2026-11-03T16:30:00",
        "end_iso": "2026-11-03T17:20:00",
        "label": "Tomorrow, 4:30 PM"
      },
      {
        "slot_id": "SLOT-A4",
        "start_iso": "2026-11-04T11:00:00",
        "end_iso": "2026-11-04T11:50:00",
        "label": "Wed 4 Nov, 11:00 AM"
      },
      {
        "slot_id": "SLOT-A5",
        "start_iso": "2026-11-04T16:00:00",
        "end_iso": "2026-11-04T16:50:00",
        "label": "Wed 4 Nov, 4:00 PM"
      }
    ]
  },
  {
    "clinician_id": "DOC-103",
    "display_name": "Dr. Maya Nambiar",
    "service_label": "Psychiatric Consultation",
    "specialty": "Psychiatry & De-addiction",
    "duration_minutes": 60,
    "fee": 3000.0,
    "slots": [
      {
        "slot_id": "SLOT-M1",
        "start_iso": "2026-11-03T11:00:00",
        "end_iso": "2026-11-03T12:00:00",
        "label": "Tomorrow, 11:00 AM"
      },
      {
        "slot_id": "SLOT-M2",
        "start_iso": "2026-11-03T17:00:00",
        "end_iso": "2026-11-03T18:00:00",
        "label": "Tomorrow, 5:00 PM"
      },
      {
        "slot_id": "SLOT-M3",
        "start_iso": "2026-11-04T14:00:00",
        "end_iso": "2026-11-04T15:00:00",
        "label": "Wed 4 Nov, 2:00 PM"
      },
      {
        "slot_id": "SLOT-M4",
        "start_iso": "2026-11-04T16:30:00",
        "end_iso": "2026-11-04T17:30:00",
        "label": "Wed 4 Nov, 4:30 PM"
      }
    ]
  },
  {
    "clinician_id": "DOC-102",
    "display_name": "Dr. Rajesh Rao",
    "service_label": "Clinical Psychology Session",
    "specialty": "Clinical Psychology & CBT",
    "duration_minutes": 45,
    "fee": 2000.0,
    "slots": [
      {
        "slot_id": "SLOT-R1",
        "start_iso": "2026-11-03T10:30:00",
        "end_iso": "2026-11-03T11:15:00",
        "label": "Tomorrow, 10:30 AM"
      },
      {
        "slot_id": "SLOT-202",
        "start_iso": "2026-11-03T14:00:00",
        "end_iso": "2026-11-03T14:45:00",
        "label": "Tomorrow, 2:00 PM"
      },
      {
        "slot_id": "SLOT-R2",
        "start_iso": "2026-11-03T16:00:00",
        "end_iso": "2026-11-03T16:45:00",
        "label": "Tomorrow, 4:00 PM"
      },
      {
        "slot_id": "SLOT-R3",
        "start_iso": "2026-11-04T12:00:00",
        "end_iso": "2026-11-04T12:45:00",
        "label": "Wed 4 Nov, 12:00 PM"
      },
      {
        "slot_id": "SLOT-R4",
        "start_iso": "2026-11-04T15:30:00",
        "end_iso": "2026-11-04T16:15:00",
        "label": "Wed 4 Nov, 3:30 PM"
      }
    ]
  }
];
  const SCENARIOS_DATA = {
  "happy": {
    "scenario": "happy",
    "status": "request_name",
    "explainer": {
      "title": "Scenario 1: Happy Path Booking",
      "badge": "Patient Choice Flow",
      "badge_color": "green",
      "problem": "Traditional clinic systems lock slots prematurely or assign arbitrary clinicians without letting patients select their preferred schedule.",
      "detection": "Real-time doctor and slot availability engine returns live bookable inventory without placing premature calendar holds.",
      "safeguard": "Patient enters their own name, reviews doctors, and only locks a 15-minute hold upon explicit confirmation. No premature holds.",
      "staff_action": "Zero manual intervention needed. System auto-confirms calendar upon verified payment webhook.",
      "patient_outcome": "Patient chooses their own clinician, session duration, and convenient time slot.",
      "action_buttons": []
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "I want to book an appointment"
      },
      {
        "from": "bot",
        "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
        "action": "request_name"
      }
    ]
  },
  "late_payment": {
    "scenario": "late_payment",
    "status": "request_name",
    "explainer": {
      "title": "Scenario 2: Late Payment / Slot Lost (P0 Exception)",
      "badge": "P0 Urgent Exception",
      "badge_color": "amber",
      "problem": "Patient completes UPI payment 16 minutes later\u2014after their 15-minute hold expired. In the meantime, another patient snatches the slot.",
      "detection": "Webhook processor detects hold expiry AND slot taken by Walk-in patient.",
      "safeguard": "Booking marked PAYMENT_RECEIVED_SLOT_LOST with P0 Urgent 15-minute SLA task.",
      "staff_action": "Staff resolves via 1-click priority reschedule or instant full UPI refund.",
      "patient_outcome": "Patient receives personalized reassurance and direct front-desk outreach.",
      "action_buttons": []
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "I want to book an appointment with Dr. Ananya Varma"
      },
      {
        "from": "bot",
        "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
        "action": "request_name"
      }
    ]
  },
  "setmore_outage": {
    "scenario": "setmore_outage",
    "status": "request_name",
    "explainer": {
      "title": "Scenario 3: Setmore 500 API Outage (P0 Exception)",
      "badge": "P0 Critical Exception",
      "badge_color": "rose",
      "problem": "Patient pays consultation fee, but Setmore calendar API crashes with 500 Internal Error.",
      "detection": "Post-payment handler traps external calendar API exception.",
      "safeguard": "Booking marked PAYMENT_CAPTURED_BOOKING_FAILED with P0 Critical 10-minute SLA task.",
      "staff_action": "Staff dashboard provides 1-click retry sync with automatic operational escalation.",
      "patient_outcome": "Patient is reassured payment was received and calendar details are being finalized.",
      "action_buttons": []
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "I want to book an appointment with Dr. Rajesh Rao"
      },
      {
        "from": "bot",
        "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
        "action": "request_name"
      }
    ]
  },
  "shared_phone": {
    "scenario": "shared_phone",
    "explainer": {
      "title": "Scenario 4: Shared Phone PIN Gate",
      "badge": "Privacy & Security",
      "badge_color": "blue",
      "problem": "Spouses or family members sharing one smartphone number risks exposing sensitive mental or sexual health records.",
      "detection": "Identity resolver detects multiple profiles mapped to a single phone number upon inbound contact.",
      "safeguard": "Clinical data is strictly isolated by PatientProfile UUID. WhatsApp displays only discreet name pills. Access requires a 4-digit PBKDF2-HMAC-SHA256 PIN. 3 failed attempts freeze the account for 15 minutes and alert staff.",
      "staff_action": "Staff dashboard flags PIN lockouts for identity verification if a patient forgets their PIN.",
      "patient_outcome": "Zero clinical diagnosis or specialty is leaked to family members sharing the smartphone.",
      "action_buttons": [
        {
          "id": "test_wrong_pin",
          "label": "Enter Wrong PIN (Test 3-Attempt Lockout)",
          "action": "test_wrong_pin",
          "color": "amber"
        },
        {
          "id": "test_correct_pin",
          "label": "Enter Correct PIN (4321 for Pooja)",
          "action": "test_correct_pin",
          "color": "emerald"
        }
      ]
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "Hi, I want to check my appointment status."
      },
      {
        "from": "bot",
        "text": "Welcome to The Bengaluru Clinic. Multiple profiles are associated with this phone number.\n\nPlease select your profile to proceed:",
        "is_profile_selector": true,
        "profiles": [
          {
            "id": "PAT-DF02C892",
            "name": "Pooja"
          },
          {
            "id": "PAT-E3D48955",
            "name": "Sameer"
          }
        ]
      }
    ],
    "profiles": [
      "PAT-DF02C892",
      "PAT-E3D48955"
    ]
  },
  "crisis": {
    "scenario": "crisis",
    "explainer": {
      "title": "Scenario 5: Psychiatric Crisis Intercept",
      "badge": "Life Safety Protocol",
      "badge_color": "rose",
      "problem": "A patient expresses acute suicidal distress or self-harm ideation inside the automated booking chat.",
      "detection": "Precision word-boundary regex matches clinical distress patterns while eliminating false positives (e.g. 'diet', 'studied').",
      "safeguard": "Automated bot AI is immediately MUTED for this patient's phone so it cannot send inappropriate automated replies. System instantly sends accredited 24/7 helpline resources (Tele-MANAS & Vandrevala Foundation).",
      "staff_action": "A P0 Urgent Task with a 5-minute SLA is spawned on the Staff Operations Cockpit for the On-Call Psychiatrist to make direct contact.",
      "patient_outcome": "Immediate access to life-saving emergency helplines and compassionate clinical intervention within minutes.",
      "action_buttons": [
        {
          "id": "resolve_crisis_btn",
          "label": "Mark Counselor Connected & Unmute AI",
          "action": "resolve_crisis",
          "color": "emerald"
        }
      ]
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "I feel completely hopeless. I can't go on anymore and I want to end my life."
      },
      {
        "from": "bot",
        "text": "We care deeply about your well-being. If you are experiencing overwhelming distress, please connect immediately with free, confidential 24/7 support:\n\n- Tele-MANAS (Govt of India): 14416 or 1800-891-4416 (Toll-Free, 24/7)\n- Vandrevala Foundation Helpline: +91 9999 666 555 (24/7)\n- Emergency Response: 112\n\nA senior clinical coordinator from The Bengaluru Clinic has also been notified and will reach out to you.",
        "is_crisis": true
      },
      {
        "from": "system",
        "text": "[SYSTEM AUDIT]: Automated AI is now MUTED for this conversation. Clinical escalation active."
      }
    ],
    "task_id": "TSK-390B86"
  },
  "lab_report": {
    "scenario": "lab_report",
    "status": "request_name",
    "explainer": {
      "title": "Scenario 6: 2FA Lab Report Vault",
      "badge": "HIPAA / DPDP Compliant",
      "badge_color": "indigo",
      "problem": "WhatsApp lock-screen notifications frequently leak sensitive medical tests to unauthorized onlookers.",
      "detection": "Patient requests lab report results or doctor clinical summary.",
      "safeguard": "No diagnosis, doctor specialty, or test names appear in the WhatsApp message. Access requires 2FA OTP verification and expires in 10 minutes. Cryptographic audit log records every access.",
      "staff_action": "Operations dashboard displays audit log of token generation, validation, and viewing IP hash.",
      "patient_outcome": "Complete peace of mind knowing medical records are shielded by multi-factor authentication.",
      "action_buttons": []
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "Can I get my latest test results?"
      },
      {
        "from": "bot",
        "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
        "action": "request_name"
      }
    ]
  }
};

  const state = {
    patient: {
      patient_id: "pat_default",
      name: "Aarav Iyer",
      first_name: "Aarav",
      phone: "+919876543210",
      greeting: "Aarav"
    },
    activeScenario: null,
    scenarioStep: 0,
    clinicians: CLINICIANS_DATA,
    activeBooking: null,
    metrics: {
      confirmed_today: 4,
      active_holds: 1,
      total_open_tasks: 2,
      p0_urgent_tasks: 0,
      p1_high_tasks: 1,
      calls_count: 3,
      emails_sent: 12
    },
    tasks: [
      {
        id: "TASK-001",
        priority: "P1",
        patient_name: "Rohan K.",
        patient_phone_masked: "+91 98765 •••••",
        description: "Scheduled callback for missed call (+91 98765 00123)",
        assigned_to: "Clinical Reception",
        due_date: new Date(Date.now() + 20 * 60000).toISOString(),
        resolution_notes: null,
        status: "OPEN"
      }
    ],
    slots: [
      {
        slot_id: "SLOT-101",
        clinician_name: "Dr. Ananya Varma",
        start_time: new Date(Date.now() + 86400000).toISOString(),
        is_booked: true,
        is_held: false,
        held_by_booking_id: "BKG-9921"
      },
      {
        slot_id: "SLOT-A2",
        clinician_name: "Dr. Ananya Varma",
        start_time: new Date(Date.now() + 92000000).toISOString(),
        is_booked: false,
        is_held: true,
        held_by_booking_id: "BKG-HOLD-15M"
      },
      {
        slot_id: "SLOT-B1",
        clinician_name: "Dr. Rajesh Rao",
        start_time: new Date(Date.now() + 100000000).toISOString(),
        is_booked: false,
        is_held: false,
        held_by_booking_id: null
      }
    ],
    calls: [
      {
        status: "MISSED",
        caller_phone: "+91 98765 00123",
        caller_phone_masked: "+91 98765 •••••",
        patient_name: "Rohan",
        timestamp: new Date(Date.now() - 15 * 60000).toISOString(),
        duration_seconds: 0,
        agent_id: "Reception-IVR"
      },
      {
        status: "ANSWERED",
        caller_phone: "+91 98450 11223",
        caller_phone_masked: "+91 98450 •••••",
        patient_name: "Pooja M.",
        timestamp: new Date(Date.now() - 45 * 60000).toISOString(),
        duration_seconds: 120,
        agent_id: "Dr. Ananya Varma"
      }
    ],
    audit_log: [
      {
        seq: 1,
        category: "SYSTEM_INIT",
        hash: "7f83b165...verified",
        timestamp: new Date().toISOString(),
        message: "The Bengaluru Clinic Operations Engine initialized. Cryptographic audit chain verified."
      }
    ]
  };

  let auditSeq = 1;
  function logAudit(category, message) {
    auditSeq++;
    const hash = Array.from(crypto.getRandomValues(new Uint8Array(8)))
      .map(b => b.toString(16).padStart(2, '0')).join('');
    state.audit_log.unshift({
      seq: auditSeq,
      category: category,
      hash: hash + "...sha256",
      timestamp: new Date().toISOString(),
      message: message
    });
    if (state.audit_log.length > 30) state.audit_log.pop();
  }

  // Intercept fetch calls for API endpoints
  const nativeFetch = window.fetch;
  window.fetch = async function (resource, options = {}) {
    const url = typeof resource === 'string' ? resource : (resource && resource.url ? resource.url : '');

    // Non-API requests pass directly to native fetch
    if (!url.includes('/api/')) {
      return nativeFetch.apply(this, arguments);
    }

    // On localhost, attempt live backend server first
    if (!isGitHubPages) {
      try {
        const response = await nativeFetch.apply(this, arguments);
        if (response.ok || response.status < 500) {
          return response;
        }
      } catch (err) {
        console.warn('[Clinic Engine] Backend unreachable at ' + url + '. Falling back to In-Browser Engine.');
      }
    }

    const method = (options.method || 'GET').toUpperCase();
    let body = {};
    if (options.body) {
      try {
        body = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
      } catch (e) { }
    }

    const path = url.split('?')[0].replace(/^.*\/api/, '/api');
    console.log('[Zero-Server API] ' + method + ' ' + path, body);

    // 1. GET /api/availability
    if (path === '/api/availability' && method === 'GET') {
      return new Response(JSON.stringify({ status: "success", clinicians: state.clinicians }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 2. GET /api/auth/me
    if (path === '/api/auth/me' && method === 'GET') {
      return new Response(JSON.stringify({
        logged_in: true,
        user: { email: "patient@bengaluru-clinic.in", name: state.patient.name }
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 3. GET /api/status
    if (path === '/api/status' && method === 'GET') {
      return new Response(JSON.stringify({
        status: "online",
        clinicians: state.clinicians.length,
        open_tasks: state.tasks.filter(t => t.status === 'OPEN').length,
        p0_tasks: state.tasks.filter(t => t.priority === 'P0' && t.status === 'OPEN').length,
        active_bookings: 3,
        emails_sent: state.metrics.emails_sent,
        active_scenario: state.activeScenario
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 4. GET /api/dashboard
    if (path === '/api/dashboard' && method === 'GET') {
      const openTasks = state.tasks.filter(t => t.status === 'OPEN');
      const p0 = openTasks.filter(t => t.priority === 'P0').length;
      const p1 = openTasks.filter(t => t.priority === 'P1').length;
      state.metrics.total_open_tasks = openTasks.length;
      state.metrics.p0_urgent_tasks = p0;
      state.metrics.p1_high_tasks = p1;

      return new Response(JSON.stringify({
        metrics: state.metrics,
        tasks: state.tasks,
        slots: state.slots,
        clinicians: state.clinicians,
        calls: state.calls,
        audit_log: state.audit_log,
        ai_muted_phones: [],
        active_scenario: state.activeScenario
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 5. POST /api/book_slot
    if (path === '/api/book_slot' && method === 'POST') {
      const clinicianId = body.clinician_id || 'DOC-101';
      const slotId = body.slot_id || 'SLOT-101';
      const clinician = state.clinicians.find(c => c.clinician_id === clinicianId) || state.clinicians[0];
      const patientName = body.patient_name || state.patient.name || 'Aarav Iyer';
      const fee = clinician ? clinician.fee : 2500;
      const bId = 'BKG-' + Math.floor(1000 + Math.random() * 9000);
      const oId = 'order_' + Math.random().toString(36).substring(2, 10);

      state.activeBooking = {
        booking_id: bId,
        order_id: oId,
        fee: fee,
        clinician_name: clinician ? clinician.display_name : 'Dr. Ananya Varma'
      };

      state.metrics.active_holds++;
      logAudit('SLOT_HOLD_ESTABLISHED', '15-minute countdown hold established for ' + patientName + ' on slot ' + slotId + '.');

      const waMsg = 'Hello ' + (state.patient.first_name || patientName.split(' ')[0]) + ', your 15-minute hold for ' + (clinician ? clinician.display_name : 'Dr. Ananya Varma') + ' has started. Please complete your payment of ₹' + Number(fee).toLocaleString() + ' via the secure link below to confirm your appointment.';

      return new Response(JSON.stringify({
        status: "success",
        booking_id: bId,
        order_id: oId,
        state: "INITIATED",
        fee: fee,
        payment_link_url: "https://rzp.io/i/sim_" + oId,
        hold_expires_at: new Date(Date.now() + 15 * 60000).toISOString(),
        whatsapp_message: waMsg,
        clinician_name: clinician ? clinician.display_name : 'Dr. Ananya Varma'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 6. POST /api/chat/message
    if (path === '/api/chat/message' && method === 'POST') {
      const text = (body.text || '').trim();
      const lower = text.toLowerCase();

      // Crisis check
      const crisisPattern = /\b(suicide|kill myself|end my life|ending it all|hang myself|slit my wrist|overdose|want to die|end it all)\b/i;
      if (crisisPattern.test(lower)) {
        state.tasks.unshift({
          id: "TASK-CRISIS-" + Date.now(),
          priority: "P0",
          patient_name: (state.patient.first_name || 'Patient') + ' (Distress Alert)',
          patient_phone_masked: "+91 98765 •••••",
          description: "CRISIS INTERCEPT: Distress language detected in WhatsApp session. Immediate psychiatric triage required.",
          assigned_to: "Duty Psychiatrist",
          due_date: new Date(Date.now() + 5 * 60000).toISOString(),
          resolution_notes: null,
          status: "OPEN"
        });
        state.metrics.p0_urgent_tasks++;
        logAudit('CRISIS_INTERCEPT', 'Distress expression detected. Bot muted. Tele-MANAS emergency lifelines sent.');

        return new Response(JSON.stringify({
          reply: 'I hear that you are going through immense emotional distress right now, ' + (state.patient.first_name || 'friend') + '. Please know that you are not alone, and help is available right now.\n\n' +
                 'Please connect immediately with trained emergency counselors:\n' +
                 '• Tele-MANAS (Govt of India 24/7): 14416 or 1800-891-4416\n' +
                 '• Vandrevala Foundation (24/7 Helpline): +91 9999 666 555\n' +
                 '• NIMHANS 24/7 Crisis Helpline: 080-46110007\n\n' +
                 'An on-duty clinical team member has been immediately alerted to offer confidential support.',
          crisis: true,
          buttons: []
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Name recognition
      if (/^[a-zA-Z\s]{2,30}$/.test(text) && !lower.includes('hello') && !lower.includes('book') && !lower.includes('fee')) {
        const parts = text.split(/\s+/);
        state.patient.name = text;
        state.patient.first_name = parts[0];
        logAudit('PATIENT_IDENTIFIED', 'Patient identified as ' + state.patient.name + '.');

        return new Response(JSON.stringify({
          reply: 'Thank you, ' + state.patient.first_name + '. Welcome to The Bengaluru Clinic. How can we support you today? Tap below to view our clinicians, schedules, and consultation fees.',
          patient: state.patient,
          kind: 'doctor_picker',
          buttons: [{ label: "Browse Clinicians & Fees", action: "open_doctor_picker" }]
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Fees inquiry
      if (lower.includes('fee') || lower.includes('cost') || lower.includes('doctor') || lower.includes('pricing')) {
        return new Response(JSON.stringify({
          reply: 'Here are our consultation fees:\n' +
                 '• Dr. Ananya Varma (Senior Clinical Psychologist) — ₹2,500 / 50 mins\n' +
                 '• Dr. Rajesh Rao (Consultant Neuropsychiatrist) — ₹3,200 / 45 mins\n' +
                 '• Ms. Kavita Raman, M.Phil (Trauma & CBT) — ₹2,200 / 50 mins\n\n' +
                 'All fees include GST exemption under Notification 12/2017-Central Tax. Would you like to select a slot?',
          buttons: [{ label: "Select Clinician & Slot", action: "open_doctor_picker" }]
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Default Friendly Reply
      return new Response(JSON.stringify({
        reply: 'Hello ' + (state.patient.first_name || 'there') + '! I am here to assist you with booking confidential appointments, checking fees, or connecting with our clinical team in Indiranagar.',
        patient: state.patient,
        buttons: [{ label: "Book Appointment", action: "open_doctor_picker" }]
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 7. POST /api/simulate/start
    if (path === '/api/simulate/start' && method === 'POST') {
      const scenarioKey = body.scenario || body.scenario_name || 'happy';
      state.activeScenario = scenarioKey;
      state.scenarioStep = 0;

      const scData = SCENARIOS_DATA[scenarioKey] || SCENARIOS_DATA['happy'];
      logAudit('SCENARIO_STARTED', 'Scenario ' + scenarioKey + ' started.');

      return new Response(JSON.stringify({
        status: "success",
        data: scData
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 8. POST /api/simulate/action
    if (path === '/api/simulate/action' && method === 'POST') {
      const action = body.action || 'pay_happy';

      if (action === 'pay_happy') {
        const fee = state.activeBooking ? state.activeBooking.fee : 2500;
        const docName = state.activeBooking ? state.activeBooking.clinician_name : 'Dr. Ananya Varma';
        const pName = state.patient.first_name || 'Aarav';

        state.metrics.confirmed_today++;
        state.metrics.active_holds = Math.max(0, state.metrics.active_holds - 1);
        state.metrics.emails_sent += 2;
        logAudit('PAYMENT_CONFIRMED', 'Payment of ₹' + Number(fee).toLocaleString() + ' captured for ' + pName + '. Appointment confirmed.');

        return new Response(JSON.stringify({
          status: "success",
          fee: fee,
          clinician_name: docName,
          confirmation_message: '✓ Payment Confirmed! Your appointment with ' + docName + ' is confirmed for Tomorrow, 10:00 AM.\n\nMode: In-Person (Suite 302, Indiranagar)\nReceipt & Tax Invoice: TBC-INV-2026-0042',
          booking: { booking_id: state.activeBooking ? state.activeBooking.booking_id : 'BKG-CONFIRMED' }
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'reschedule_slot_lost') {
        state.tasks.unshift({
          id: "TASK-RESCHED-" + Date.now(),
          priority: "P0",
          patient_name: "Aarav (****3210)",
          patient_phone_masked: "+91 98765 •••••",
          description: "SLOT LOST: Alternate priority slot offered and accepted.",
          assigned_to: "Clinic Manager",
          due_date: new Date(Date.now() + 15 * 60000).toISOString(),
          resolution_notes: "Rebooked for 02:00 PM",
          status: "RESOLVED"
        });
        logAudit('SLOT_LOST_RESCHEDULED', 'Patient Aarav rescheduled to alternate slot SLOT-A3.');
        return new Response(JSON.stringify({
          status: "success",
          whatsapp_message: 'Your payment was applied to the alternate priority slot: Tomorrow at 02:00 PM with Dr. Ananya Varma. Updated confirmation dispatched.'
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'retry_booking') {
        logAudit('SETMORE_SYNC_RECOVERED', 'Setmore calendar outage resolved. Appointment synched.');
        return new Response(JSON.stringify({
          status: "resolved",
          result: { success: true, message: "Calendar synched cleanly." }
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'test_wrong_pin') {
        return new Response(JSON.stringify({
          success: false,
          message: "Incorrect PIN (Attempt 1 of 3). Please verify your 4-digit security PIN."
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'test_correct_pin') {
        logAudit('PIN_VERIFIED', 'PIN 4321 verified. Discrete session unlocked for Pooja.');
        return new Response(JSON.stringify({
          success: true,
          message: "PIN verified successfully. Confidential session unlocked for Pooja."
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'resolve_crisis') {
        logAudit('CRISIS_RESOLVED', 'On-call psychiatrist connected with patient. AI bot unmuted.');
        return new Response(JSON.stringify({
          status: "resolved",
          result: { success: true, message: "Counselor connected. Bot unmuted." }
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (action === 'verify_lab_otp') {
        logAudit('2FA_VAULT_UNLOCKED', '2FA OTP verified. Secure lab reports opened.');
        return new Response(JSON.stringify({
          status: "success",
          message: "2FA Authenticated: Secure Lab Report Vault Unlocked."
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      return new Response(JSON.stringify({ status: "success" }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 9. POST /api/simulate/reset
    if (path === '/api/simulate/reset' && method === 'POST') {
      state.activeScenario = null;
      state.metrics.confirmed_today = 4;
      state.metrics.active_holds = 1;
      logAudit('SYSTEM_RESET', 'Simulation state reset to clean baseline.');

      return new Response(JSON.stringify({ status: "reset_complete" }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 10. POST /api/call/inbound
    if (path === '/api/call/inbound' && method === 'POST') {
      state.metrics.calls_count++;
      state.tasks.unshift({
        id: "TASK-CALL-" + Date.now(),
        priority: "P1",
        patient_name: "Inbound Caller",
        patient_phone_masked: "+91 98765 •••••",
        description: 'Missed call callback task for ' + (body.phone || '+91 98765 43210'),
        assigned_to: "Reception Frontdesk",
        due_date: new Date(Date.now() + 30 * 60000).toISOString(),
        resolution_notes: null,
        status: "OPEN"
      });
      state.metrics.p1_high_tasks++;
      logAudit('INBOUND_CALL', 'Inbound missed call received. P1 30-minute callback task scheduled.');

      return new Response(JSON.stringify({
        status: "recorded",
        message: "Inbound missed call logged. Callback scheduled with 30-min SLA."
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    // Fallback response
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
})();
