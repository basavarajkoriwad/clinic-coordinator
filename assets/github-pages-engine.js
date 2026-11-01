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

  console.log(`[Clinic Engine] Host: ${window.location.hostname}. Zero-Server Engine: ${isGitHubPages ? 'ACTIVE (GitHub Pages)' : 'HYBRID (Fallback)'}`);

  // In-Memory Simulation State
  const state = {
    patient: {
      patient_id: "pat_default",
      name: "Aarav Iyer",
      first_name: "Aarav",
      phone: "+91 98765 43210",
      greeting: "Aarav"
    },
    currentScenario: 1,
    scenarioStep: 0,
    clinicians: [
      {
        id: "c1",
        name: "Dr. Ananya Rao",
        title: "Senior Clinical Psychologist (CBT & Relationships)",
        consultation_fee: 2500,
        duration_minutes: 50,
        available_slots: [
          { slot_id: "s1_1", time: "Tomorrow at 10:00 AM", iso_time: "2026-11-03T10:00:00" },
          { slot_id: "s1_2", time: "Tomorrow at 11:30 AM", iso_time: "2026-11-03T11:30:00" },
          { slot_id: "s1_3", time: "Tomorrow at 02:00 PM", iso_time: "2026-11-03T14:00:00" }
        ]
      },
      {
        id: "c2",
        name: "Dr. Vikramaditya Sen",
        title: "Consultant Neuropsychiatrist (Medical Evaluations)",
        consultation_fee: 3200,
        duration_minutes: 45,
        available_slots: [
          { slot_id: "s2_1", time: "Tomorrow at 04:30 PM", iso_time: "2026-11-03T16:30:00" },
          { slot_id: "s2_2", time: "Day After at 11:00 AM", iso_time: "2026-11-04T11:00:00" }
        ]
      },
      {
        id: "c3",
        name: "Ms. Kavita Raman, M.Phil",
        title: "Licensed Clinical Psychologist (Sexual Health & Trauma)",
        consultation_fee: 2200,
        duration_minutes: 50,
        available_slots: [
          { slot_id: "s3_1", time: "Day After at 02:30 PM", iso_time: "2026-11-04T14:30:00" },
          { slot_id: "s3_2", time: "Day After at 05:00 PM", iso_time: "2026-11-04T17:00:00" }
        ]
      }
    ],
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
        slot_id: "SLOT-001",
        clinician_name: "Dr. Ananya Rao",
        start_time: new Date(Date.now() + 86400000).toISOString(),
        is_booked: true,
        is_held: false,
        held_by_booking_id: "BKG-9921"
      },
      {
        slot_id: "SLOT-002",
        clinician_name: "Dr. Ananya Rao",
        start_time: new Date(Date.now() + 92000000).toISOString(),
        is_booked: false,
        is_held: true,
        held_by_booking_id: "BKG-HOLD-15M"
      },
      {
        slot_id: "SLOT-003",
        clinician_name: "Dr. Vikramaditya Sen",
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
        agent_id: "Dr. Ananya Rao"
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
        console.warn(`[Clinic Engine] Backend unreachable at ${url}. Falling back to In-Browser Engine.`);
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
    console.log(`[Zero-Server API] ${method} ${path}`, body);

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
        active_scenario: state.currentScenario
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
        active_scenario: state.currentScenario
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 5. POST /api/chat/message
    if (path === '/api/chat/message' && method === 'POST') {
      const text = (body.text || '').trim();
      const lower = text.toLowerCase();

      // Crisis check
      const crisisPattern = /\b(suicide|kill myself|end my life|ending it all|hang myself|slit my wrist|overdose|want to die|end it all)\b/i;
      if (crisisPattern.test(lower)) {
        state.tasks.unshift({
          id: "TASK-CRISIS-" + Date.now(),
          priority: "P0",
          patient_name: `${state.patient.first_name} (Distress Alert)`,
          patient_phone_masked: "+91 98765 •••••",
          description: "CRISIS INTERCEPT: Distress language detected in WhatsApp session. Immediate psychiatric triage required.",
          assigned_to: "Duty Psychiatrist",
          due_date: new Date(Date.now() + 5 * 60000).toISOString(),
          resolution_notes: null,
          status: "OPEN"
        });
        state.metrics.p0_urgent_tasks++;
        logAudit("CRISIS_INTERCEPT", `Distress message intercepted. Bot muted. Tele-MANAS emergency lifelines sent to ${state.patient.first_name}.`);

        return new Response(JSON.stringify({
          reply: `I hear that you are going through immense emotional distress right now, ${state.patient.first_name}. Please know that you are not alone, and help is available right now.\n\n` +
                 `Please connect immediately with trained emergency counselors:\n` +
                 `• Tele-MANAS (Govt of India 24/7): 14416 or 1800-891-4416\n` +
                 `• Vandrevala Foundation (24/7 Helpline): +91 9999 666 555\n` +
                 `• NIMHANS 24/7 Crisis Helpline: 080-46110007\n\n` +
                 `An on-duty clinical staff member has been alerted immediately to offer support.`,
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
        logAudit("PATIENT_IDENTIFIED", `Patient identified as ${state.patient.name}. Profile initialized.`);

        return new Response(JSON.stringify({
          reply: `Thank you, ${state.patient.first_name}. Welcome to The Bengaluru Clinic. How can we support you today? Tap below to view our clinicians, schedules, and consultation fees.`,
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
          reply: `Here are our clinical consultation fees:\n` +
                 `• Dr. Ananya Rao (Senior Clinical Psychologist, CBT) — ₹2,500 / 50 mins\n` +
                 `• Dr. Vikramaditya Sen (Consultant Neuropsychiatrist) — ₹3,200 / 45 mins\n` +
                 `• Ms. Kavita Raman, M.Phil (Sexual Health & Trauma) — ₹2,200 / 50 mins\n\n` +
                 `All fees include GST exemption under Notification 12/2017-Central Tax. Would you like to reserve an appointment?`,
          buttons: [{ label: "Select Clinician & Slot", action: "open_doctor_picker" }]
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Default friendly response
      return new Response(JSON.stringify({
        reply: `Hello ${state.patient.first_name || 'there'}! I am here to assist you with booking confidential appointments, checking fees, or connecting with our team in Indiranagar.`,
        patient: state.patient,
        buttons: [{ label: "Book Appointment", action: "open_doctor_picker" }]
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 6. POST /api/book_slot
    if (path === '/api/book_slot' && method === 'POST') {
      state.metrics.active_holds++;
      logAudit("SLOT_HOLD_ESTABLISHED", `15-minute countdown hold established for ${state.patient.first_name} on slot ${body.slot_id || 'SLOT-002'}.`);

      return new Response(JSON.stringify({
        status: "held",
        hold_id: "hold_" + Math.random().toString(36).substring(2, 8),
        expires_in_seconds: 900,
        message: `Temporary 15-minute hold established for ${state.patient.first_name}. Please complete payment before the hold expires.`,
        payment_amount: 2500,
        clinician_name: "Dr. Ananya Rao"
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 7. POST /api/simulate/start
    if (path === '/api/simulate/start' && method === 'POST') {
      const sId = parseInt(body.scenario_id || 1, 10);
      state.currentScenario = sId;
      state.scenarioStep = 0;

      const scenarios = {
        1: {
          title: "Happy Path Booking",
          intro: "Welcome to The Bengaluru Clinic. To begin your confidential booking, please enter your name.",
          action_label: "Start Booking Flow"
        },
        2: {
          title: "Late Payment / Slot Lost (P0)",
          intro: "Hello, this is The Bengaluru Clinic. Your 15-minute slot hold has expired due to pending payment.",
          action_label: "Simulate Late Payment Capture"
        },
        3: {
          title: "Setmore 500 Outage (P0)",
          intro: "Your payment of ₹2,500 was captured, but Setmore calendar synchronization returned a 500 server error.",
          action_label: "Trigger 500 Outage & Auto-Extension"
        },
        4: {
          title: "Shared Phone PIN Privacy Gate",
          intro: "Incoming message from a shared family phone (+91 98765 00000). Please enter your 4-digit privacy PIN.",
          action_label: "Submit PIN (4321 for Pooja)"
        },
        5: {
          title: "Psychiatric Crisis Intercept",
          intro: "Patient sends a high-distress message containing safety trigger keywords.",
          action_label: "Send Distress Message"
        },
        6: {
          title: "Name Persistence Throughout Session",
          intro: "Patient Aarav Iyer enters details once. Name persists across all booking and payment steps.",
          action_label: "Verify Name Persistence"
        }
      };

      const sc = scenarios[sId] || scenarios[1];
      logAudit("SCENARIO_STARTED", `Scenario ${sId}: ${sc.title} started.`);

      return new Response(JSON.stringify({
        status: "ok",
        scenario_id: sId,
        title: sc.title,
        message: sc.intro,
        action_label: sc.action_label,
        patient: state.patient
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 8. POST /api/simulate/action
    if (path === '/api/simulate/action' && method === 'POST') {
      state.scenarioStep++;
      const sId = state.currentScenario;

      if (sId === 2) { // Late Payment Slot Lost
        state.tasks.unshift({
          id: "TASK-LOST-" + Date.now(),
          priority: "P0",
          patient_name: "Aarav (****3210)",
          patient_phone_masked: "+91 98765 •••••",
          description: "SLOT LOST EXCEPTION: Payment captured after 15m hold expired. Alternate slot priority booking required.",
          assigned_to: "Clinic Manager",
          due_date: new Date(Date.now() + 15 * 60000).toISOString(),
          resolution_notes: null,
          status: "OPEN"
        });
        state.metrics.p0_urgent_tasks++;
        logAudit("SLOT_LOST_P0", "Payment captured on expired hold. Alternate priority slot assigned; staff notified.");

        return new Response(JSON.stringify({
          status: "exception_handled",
          reply: `Aarav, your payment of ₹2,500 was successfully captured. However, the 15-minute hold expired and your original slot was reserved. We have assigned you priority queue status and our clinic manager has been notified.`,
          badge: "P0 Exception Active",
          next_action: "Review Staff Cockpit"
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      if (sId === 3) { // Setmore 500 Outage
        state.tasks.unshift({
          id: "TASK-SETMORE-" + Date.now(),
          priority: "P0",
          patient_name: "Aarav (****3210)",
          patient_phone_masked: "+91 98765 •••••",
          description: "SETMORE 500 OUTAGE: Hold auto-extended by 60 mins. Manual sync required when API recovers.",
          assigned_to: "Senior Reception",
          due_date: new Date(Date.now() + 30 * 60000).toISOString(),
          resolution_notes: null,
          status: "OPEN"
        });
        state.metrics.p0_urgent_tasks++;
        logAudit("SETMORE_500_OUTAGE", "Setmore API responded 500. Slot hold extended by 60 mins to protect patient booking.");

        return new Response(JSON.stringify({
          status: "calendar_failure_handled",
          reply: `Aarav, your payment of ₹2,500 is confirmed! Our calendar sync provider is currently experiencing an outage. Your appointment has been secured with an extended 60-minute hold.`,
          badge: "Hold Extended +60m",
          next_action: "Retry Sync in Staff Cockpit"
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      if (sId === 4) { // Shared Phone PIN
        logAudit("PIN_VERIFIED", "PIN 4321 verified. Discrete confidential session unlocked for Pooja.");
        return new Response(JSON.stringify({
          status: "pin_verified",
          reply: `Welcome back, Pooja. Your session is securely unlocked. You have an upcoming consultation with Dr. Ananya Rao tomorrow at 11:30 AM.`,
          badge: "PIN Verified"
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      if (sId === 5) { // Crisis
        return window.fetch('/api/chat/message', {
          method: 'POST',
          body: JSON.stringify({ text: "I can't go on anymore, feeling like ending it all" })
        });
      }

      // Default happy path confirmation
      state.metrics.confirmed_today++;
      state.metrics.active_holds = Math.max(0, state.metrics.active_holds - 1);
      state.metrics.emails_sent += 2;
      logAudit("BOOKING_CONFIRMED", `Booking confirmed for ${state.patient.first_name} with Dr. Ananya Rao. Tax invoice generated.`);

      return new Response(JSON.stringify({
        status: "confirmed",
        reply: `Payment of ₹2,500 received! Your appointment with Dr. Ananya Rao is confirmed for Tomorrow at 10:00 AM. Tax invoice and preparation instructions have been dispatched.`,
        badge: "Confirmed"
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    // 9. POST /api/simulate/reset
    if (path === '/api/simulate/reset' && method === 'POST') {
      state.metrics.confirmed_today = 4;
      state.metrics.active_holds = 1;
      logAudit("SYSTEM_RESET", "Simulation state reset to clean baseline.");

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
        description: `Missed call callback task for ${body.phone || '+91 98765 43210'}`,
        assigned_to: "Reception Frontdesk",
        due_date: new Date(Date.now() + 30 * 60000).toISOString(),
        resolution_notes: null,
        status: "OPEN"
      });
      state.metrics.p1_high_tasks++;
      logAudit("INBOUND_CALL", `Inbound missed call received. P1 30-minute callback task scheduled.`);

      return new Response(JSON.stringify({
        status: "recorded",
        message: "Inbound missed call logged. Callback scheduled with 30-min SLA."
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    // Default fallback
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
})();
