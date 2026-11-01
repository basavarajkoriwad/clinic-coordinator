/**
 * The Bengaluru Clinic - Client-Side Simulation Engine for GitHub Pages
 * ====================================================================
 * 100% In-Browser Simulation Engine providing complete parity with Python backend:
 * - Real clinician list with live fees and appointment slot chips
 * - Full 15-minute hold lifecycle, order creation & Razorpay modal checkout
 * - Complete execution for all 6 simulator scenarios:
 *     1. Happy Path Booking
 *     2. Late Payment / Slot Lost (P0 Exception with Reschedule / Refund actions)
 *     3. Setmore 500 Outage (P0 Exception with Calendar Retry Sync)
 *     4. Shared Phone PIN Gate (Wrong PIN lockout & Correct PIN auth)
 *     5. Psychiatric Crisis Intercept (P0 Safety Regex, Tele-MANAS lifelines & bot mute)
 *     6. 2FA Lab Report Vault (OTP verification & secure vault unlock)
 * - Live Staff Operations Cockpit polling (metrics, tasks, calendar slots, calls, audit log)
 * - Cross-window state synchronization between WhatsApp simulator & embedded Staff Cockpit
 */

(function () {
  const isGitHubPages = window.location.hostname.endsWith('github.io') ||
                        window.location.protocol === 'file:' ||
                        window.__FORCE_CLIENT_MOCK__ === true;

  console.log('[Clinic Engine] Standalone Mode: ' + (isGitHubPages ? 'ACTIVE (GitHub Pages)' : 'HYBRID (Fallback)'));

  // Database of Scenarios & Clinicians
  const AVAILABILITY_DATA = [
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
  const SCENARIOS_START_DATA = {
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
            "id": "PAT-49D347B8",
            "name": "Pooja"
          },
          {
            "id": "PAT-D487B202",
            "name": "Sameer"
          }
        ]
      }
    ],
    "profiles": [
      "PAT-49D347B8",
      "PAT-D487B202"
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
    "task_id": "TSK-6DFB83"
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
  const SCENARIOS_RESUME_DATA = {
  "late_payment": {
    "scenario": "late_payment",
    "explainer": {
      "title": "Scenario 2: Late Payment / Slot Lost (P0 Exception)",
      "badge": "P0 Urgent Exception",
      "badge_color": "amber",
      "problem": "Patient (Aarav) completed UPI payment 16 minutes later\u2014after their 15-minute hold expired. In the meantime, Walk-in patient took the slot.",
      "detection": "Webhook processor caught that hold expired AND slot.is_booked by another patient, preventing a calendar collision.",
      "safeguard": "Booking transitioned to PAYMENT_RECEIVED_SLOT_LOST. Generated a P0 Urgent Staff Task with a 15-minute SLA. Sent a reassuring WhatsApp message to the patient.",
      "staff_action": "Staff must resolve this immediately: either reschedule to the next priority slot or trigger an instant full refund.",
      "patient_outcome": "Instead of a double-booking conflict or generic payment error, the patient was reassured that the clinic manager is handling their booking personally.",
      "action_buttons": [
        {
          "id": "reschedule_btn",
          "label": "Reschedule to Alternate Slot (SLOT-103)",
          "action": "reschedule_slot_lost",
          "new_slot_id": "SLOT-103",
          "color": "emerald"
        },
        {
          "id": "refund_btn",
          "label": "Issue Instant Full Refund (\u20b9 2,500)",
          "action": "refund_slot_lost",
          "color": "rose"
        }
      ]
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "I'd like to book with Dr. Ananya Varma."
      },
      {
        "from": "bot",
        "text": "Hello Aarav. Please complete your payment using the secure link below:\n\nhttps://pay.bengaluru-clinic.in/pay/order_bkg_9942470b\n\nPlease note: You have 15 minutes to complete the payment. If payment is not completed within 15 minutes, your temporary hold will expire automatically and the appointment slot will be released.\n\nYour appointment confirmation will be sent immediately after successful payment."
      },
      {
        "from": "bot",
        "text": "Hello Aarav. Your 15-minute payment window has ended, and the temporary hold has been released.\n\nIf you still wish to schedule an appointment, please reply or choose from available slots to book again."
      },
      {
        "from": "patient",
        "text": "[Aarav pays via UPI link 16 mins later after slot was given to someone else]"
      },
      {
        "from": "bot",
        "text": "Hello Aarav. We received your payment (Ref: pay_a566efe1a5). Due to high demand, our clinic manager is personally finalizing your slot and will call you in 15 minutes."
      }
    ],
    "booking_id": "BKG-9942470B",
    "task_id": "TSK-6DDA1F",
    "patient": {
      "patient_id": "PAT-8B2F5CEE",
      "name": "Aarav Iyer",
      "first_name": "Aarav",
      "phone": "+919876543210"
    }
  },
  "setmore_outage": {
    "scenario": "setmore_outage",
    "explainer": {
      "title": "Scenario 3: Setmore 500 API Outage (P0 Exception)",
      "badge": "P0 Critical Exception",
      "badge_color": "rose",
      "problem": "Patient (Aarav) paid \u20b9 2,000, but Setmore calendar API crashed with a 500 Internal Timeout during CalDAV synchronization.",
      "detection": "Webhook handler caught the unhandled calendar API exception post-payment capture.",
      "safeguard": "Booking marked PAYMENT_CAPTURED_BOOKING_FAILED. Created a P0 Critical Task with a 10-minute SLA for Clinic Manager. Patient reassured that payment was captured.",
      "staff_action": "Staff dashboard provides a 1-click 'Retry Calendar Sync'. If retried twice without success, the task auto-escalates to senior operations.",
      "patient_outcome": "Patient is not left wondering why their card was charged with no confirmation. They are notified that their calendar slot is being finalized shortly.",
      "action_buttons": [
        {
          "id": "retry_setmore_btn",
          "label": "1-Click Retry Calendar Sync",
          "action": "retry_booking",
          "color": "indigo"
        }
      ]
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "Booking appointment with Dr. Rajesh Rao."
      },
      {
        "from": "bot",
        "text": "Hello Aarav. Please complete your payment using the secure link below:\n\nhttps://pay.bengaluru-clinic.in/pay/order_bkg_e75ebb5f\n\nPlease note: You have 15 minutes to complete the payment. If payment is not completed within 15 minutes, your temporary hold will expire automatically and the appointment slot will be released.\n\nYour appointment confirmation will be sent immediately after successful payment."
      },
      {
        "from": "patient",
        "text": "[Aarav successfully completes payment of \u20b9 2,000]"
      },
      {
        "from": "bot",
        "text": "Hello Aarav. Your payment of \u20b9 2,000 was received successfully. Your appointment is being registered on the clinician's calendar. You will receive final calendar details shortly."
      }
    ],
    "booking_id": "BKG-E75EBB5F",
    "task_id": "TSK-9EF802",
    "patient": {
      "patient_id": "PAT-8B2F5CEE",
      "name": "Aarav Iyer",
      "first_name": "Aarav",
      "phone": "+919876543210"
    }
  },
  "lab_report": {
    "scenario": "lab_report",
    "explainer": {
      "title": "Scenario 6: 2FA Lab Report Vault",
      "badge": "HIPAA / DPDP Compliant",
      "badge_color": "indigo",
      "problem": "WhatsApp lock-screen notifications frequently leak sensitive medical tests to unauthorized onlookers.",
      "detection": "Patient requests lab report results or doctor clinical summary.",
      "safeguard": "No diagnosis, doctor specialty, or test names appear in the WhatsApp message. Access requires 2FA OTP verification and expires in 10 minutes. Cryptographic audit log records every access.",
      "staff_action": "Operations dashboard displays audit log of token generation, validation, and viewing IP hash.",
      "patient_outcome": "Complete peace of mind knowing medical records are shielded by multi-factor authentication.",
      "action_buttons": [
        {
          "id": "verify_otp_btn",
          "label": "Verify 2FA OTP (729401) & Open Secure Vault",
          "action": "verify_lab_otp",
          "color": "indigo"
        }
      ]
    },
    "chat_messages": [
      {
        "from": "patient",
        "text": "Can I get my latest test results?"
      },
      {
        "from": "bot",
        "text": "Hello Aarav. Your secure health documents are ready.\n\nFor your medical privacy, access requires two-factor verification. Your 6-digit access code is: 729401 (Valid for 10 minutes).\n\nSecure Vault Link: https://vault.bengaluru-clinic.in/r/v2?auth=729401"
      }
    ],
    "otp": "729401",
    "patient": {
      "patient_id": "PAT-8B2F5CEE",
      "name": "Aarav Iyer",
      "first_name": "Aarav",
      "phone": "+919876543210"
    }
  }
};
  const ACTIONS_DATA = {
  "pay_happy": {
    "status": "success",
    "fee": 2500.0,
    "clinician_name": "Dr. Ananya Varma",
    "confirmation_message": "\u2713 Appointment Confirmed with Dr. Ananya Varma for Aarav.\n\nMode: In-Person (Suite 302, Indiranagar)\nReceipt & Tax Invoice: TBC-INV-2026-0042",
    "booking": {
      "booking_id": "BKG-CONFIRMED"
    }
  },
  "reschedule_slot_lost": {
    "status": "success",
    "whatsapp_message": "Hello Aarav. Your appointment has been rescheduled to tomorrow at 3:00 PM with Dr. Ananya Varma. Thank you for your patience."
  },
  "refund_slot_lost": {
    "status": "success",
    "whatsapp_message": "Hello Aarav. An instant full refund of \u20b9 2,500 has been processed to your UPI account. Reference: RFD-UPI-9921."
  },
  "retry_booking": {
    "status": "resolved",
    "message": "Appointment confirmed on calendar. Confirmation details dispatched."
  },
  "test_wrong_pin": {
    "success": false,
    "message": "Incorrect PIN (Attempt 1 of 3). Please verify your 4-digit security PIN."
  },
  "test_correct_pin": {
    "success": true,
    "message": "PIN verified successfully. Confidential session unlocked for Pooja."
  },
  "resolve_crisis": {
    "status": "resolved",
    "message": "Counselor connected. Bot unmuted."
  },
  "verify_lab_otp": {
    "status": "success",
    "report_url": "https://vault.bengaluru-clinic.in/report/LAB-2026-992?token=auth_exp_10m",
    "message": "2FA Authenticated: Secure Medical Vault Unlocked."
  }
};

  function createInitialState() {
    return {
      patient: {
        patient_id: "pat_aarav_01",
        name: "Aarav Iyer",
        first_name: "Aarav",
        phone: "+919876543210",
        greeting: "Aarav"
      },
      activeScenario: null,
      scenarioStep: 0,
      clinicians: AVAILABILITY_DATA,
      activeBooking: null,
      metrics: {
        confirmed_count: 4,
        confirmed_today: 4,
        active_holds: 1,
        total_open_tasks: 1,
        p0_urgent_tasks: 0,
        p1_high_tasks: 1,
        calls_count: 3,
        emails_sent: 12
      },
      tasks: [
        {
          task_id: "TASK-001",
          id: "TASK-001",
          priority: "P1_HIGH",
          status: "OPEN",
          title: "Scheduled Callback for Missed Call",
          description: "Scheduled callback for missed call (+91 98765 •••••)",
          patient_name: "Rohan K.",
          patient_phone_masked: "+91 98765 •••••",
          assigned_to: "Clinical Reception",
          due_date: new Date(Date.now() + 20 * 60000).toISOString(),
          is_overdue: false,
          time_left_seconds: 1200,
          resolved_at: null,
          resolution_notes: null
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
          category: "SYSTEM",
          hash: "7f83b165...verified",
          timestamp: new Date().toISOString(),
          message: "The Bengaluru Clinic Operations Engine initialized. Cryptographic audit chain verified."
        }
      ]
    };
  }

  // Shared state helper between parent window and embedded iframe
  function getSharedState() {
    try {
      if (window.top && window.top.__CLINIC_SHARED_STATE__) {
        return window.top.__CLINIC_SHARED_STATE__;
      }
    } catch (e) { }

    try {
      const stored = sessionStorage.getItem('__CLINIC_STATE__');
      if (stored) {
        const parsed = JSON.parse(stored);
        try { if (window.top) window.top.__CLINIC_SHARED_STATE__ = parsed; } catch (e) { }
        return parsed;
      }
    } catch (e) { }

    const initial = createInitialState();
    try {
      if (window.top) window.top.__CLINIC_SHARED_STATE__ = initial;
      sessionStorage.setItem('__CLINIC_STATE__', JSON.stringify(initial));
    } catch (e) { }
    return initial;
  }

  function saveSharedState(s) {
    try {
      if (window.top) window.top.__CLINIC_SHARED_STATE__ = s;
      sessionStorage.setItem('__CLINIC_STATE__', JSON.stringify(s));
    } catch (e) { }
  }

  const state = getSharedState();

  let auditSeq = state.audit_log.length ? state.audit_log[0].seq : 1;
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
    if (state.audit_log.length > 35) state.audit_log.pop();
    saveSharedState(state);
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
        console.warn('[Clinic Engine] Local backend offline. Using In-Browser Engine for ' + url);
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
        p0_tasks: state.tasks.filter(t => t.priority === 'P0_URGENT' && t.status === 'OPEN').length,
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
      // Refresh state from storage in case parent updated it
      const current = getSharedState();
      const openTasks = current.tasks.filter(t => t.status === 'OPEN');
      const p0 = openTasks.filter(t => t.priority === 'P0_URGENT' || t.priority === 'P0').length;
      const p1 = openTasks.filter(t => t.priority === 'P1_HIGH' || t.priority === 'P1').length;
      current.metrics.total_open_tasks = openTasks.length;
      current.metrics.p0_urgent_tasks = p0;
      current.metrics.p1_high_tasks = p1;

      return new Response(JSON.stringify({
        metrics: current.metrics,
        tasks: current.tasks,
        slots: current.slots,
        clinicians: current.clinicians,
        calls: current.calls,
        audit_log: current.audit_log,
        ai_muted_phones: [],
        active_scenario: current.activeScenario
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
      logAudit('BOOKING', '15-minute countdown hold established for ' + patientName + ' on slot ' + slotId + '.');

      const waMsg = 'Hello ' + (state.patient.first_name || patientName.split(' ')[0]) + ', your 15-minute hold for ' + (clinician ? clinician.display_name : 'Dr. Ananya Varma') + ' has started. Please complete your payment of ₹' + Number(fee).toLocaleString() + ' via the secure link below to confirm your appointment.';

      saveSharedState(state);

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

      // Crisis regex check
      const crisisPattern = /\b(suicide|kill myself|end my life|ending it all|hang myself|slit my wrist|overdose|want to die|end it all)\b/i;
      if (crisisPattern.test(lower)) {
        state.tasks.unshift({
          task_id: "TASK-CRISIS-" + Date.now().toString().slice(-4),
          id: "TASK-CRISIS-" + Date.now().toString().slice(-4),
          priority: "P0_URGENT",
          status: "OPEN",
          title: "CRISIS INTERCEPT: Distress Expression Detected",
          patient_name: (state.patient.first_name || 'Patient') + ' (Distress Alert)',
          patient_phone_masked: "+91 98765 •••••",
          description: "CRISIS INTERCEPT: Distress language detected in WhatsApp session. Immediate psychiatric triage required.",
          assigned_to: "Duty Psychiatrist",
          due_date: new Date(Date.now() + 5 * 60000).toISOString(),
          is_overdue: false,
          time_left_seconds: 300,
          resolved_at: null,
          resolution_notes: null
        });
        state.metrics.p0_urgent_tasks++;
        logAudit('CRISIS', 'Distress expression detected. Bot muted. Tele-MANAS emergency lifelines sent.');
        saveSharedState(state);

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

      // Patient typed their name
      if (/^[a-zA-Z\s]{2,30}$/.test(text) && !lower.includes('hello') && !lower.includes('book') && !lower.includes('fee')) {
        const parts = text.split(/\s+/);
        state.patient.name = text;
        state.patient.first_name = parts[0];
        logAudit('BOOKING', 'Patient identified as ' + state.patient.name + '.');

        // Check if an interactive scenario was waiting for patient name (Scenario 2, 3, or 6)
        if (state.activeScenario && SCENARIOS_RESUME_DATA[state.activeScenario]) {
          const resData = JSON.parse(JSON.stringify(SCENARIOS_RESUME_DATA[state.activeScenario]));
          resData.patient = {
            patient_id: state.patient.patient_id,
            name: state.patient.name,
            first_name: state.patient.first_name,
            phone: state.patient.phone
          };

          if (state.activeScenario === 'late_payment') {
            state.tasks.unshift({
              task_id: "TASK-LATE-" + Date.now().toString().slice(-4),
              id: "TASK-LATE-" + Date.now().toString().slice(-4),
              priority: "P0_URGENT",
              status: "OPEN",
              title: "SLOT LOST: Payment Received After Hold Expiration",
              patient_name: state.patient.name + " (+91 98765 3210)",
              patient_phone_masked: "+91 98765 •••••",
              description: "Patient Aarav paid ₹2,500 after 15-minute hold expired. Slot SLOT-101 was released to another patient.",
              assigned_to: "Duty Clinical Coordinator",
              due_date: new Date(Date.now() + 10 * 60000).toISOString(),
              is_overdue: false,
              time_left_seconds: 600,
              resolved_at: null,
              resolution_notes: null
            });
            state.metrics.p0_urgent_tasks++;
            logAudit('BOOKING', 'P0 Task raised: Late payment detected for slot SLOT-101. Hold expired.');
          } else if (state.activeScenario === 'setmore_outage') {
            state.tasks.unshift({
              task_id: "TASK-SETMORE-" + Date.now().toString().slice(-4),
              id: "TASK-SETMORE-" + Date.now().toString().slice(-4),
              priority: "P0_URGENT",
              status: "OPEN",
              title: "SETMORE SYNC FAILED: Calendar API 500 Outage",
              patient_name: state.patient.name,
              patient_phone_masked: "+91 98765 •••••",
              description: "Setmore Calendar API returned 500 Internal Server Error. Fallback queue captured booking.",
              assigned_to: "Technical Operations",
              due_date: new Date(Date.now() + 15 * 60000).toISOString(),
              is_overdue: false,
              time_left_seconds: 900,
              resolved_at: null,
              resolution_notes: null
            });
            state.metrics.p0_urgent_tasks++;
            logAudit('SYSTEM', 'P0 Task raised: Setmore API 500 outage. Fallback booking buffered.');
          }

          logAudit('BOOKING', 'Scenario ' + state.activeScenario + ' resumed for ' + state.patient.name);
          saveSharedState(state);

          return new Response(JSON.stringify({
            status: "scenario_resume",
            kind: "scenario_resume",
            data: resData,
            ...resData
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        // Default: Open Doctor Picker for Happy Path
        saveSharedState(state);
        return new Response(JSON.stringify({
          status: "success",
          kind: "doctor_picker",
          reply: 'Thank you, ' + state.patient.first_name + '. Welcome to The Bengaluru Clinic. How can we support you today? Tap below to view our clinicians, schedules, and consultation fees.',
          patient: state.patient,
          clinicians: state.clinicians,
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

      if (scenarioKey === 'crisis') {
        state.tasks.unshift({
          task_id: "TASK-CRISIS-" + Date.now().toString().slice(-4),
          id: "TASK-CRISIS-" + Date.now().toString().slice(-4),
          priority: "P0_URGENT",
          status: "OPEN",
          title: "CRISIS INTERCEPT: Immediate Psychiatric Triage Required",
          patient_name: "Patient (Distress Alert)",
          patient_phone_masked: "+91 98765 •••••",
          description: "CRISIS INTERCEPT: Distress language detected in WhatsApp session. Immediate psychiatric triage required.",
          assigned_to: "Duty Psychiatrist",
          due_date: new Date(Date.now() + 5 * 60000).toISOString(),
          is_overdue: false,
          time_left_seconds: 300,
          resolved_at: null,
          resolution_notes: null
        });
        state.metrics.p0_urgent_tasks++;
        logAudit('CRISIS', 'Psychiatric crisis scenario started. Distress language detected. Bot muted.');
      } else if (scenarioKey === 'shared_phone') {
        logAudit('SECURITY', 'Shared phone PIN gate scenario started. PIN authentication challenge dispatched.');
      } else {
        logAudit('SYSTEM', 'Scenario ' + scenarioKey + ' started.');
      }

      saveSharedState(state);

      const scData = SCENARIOS_START_DATA[scenarioKey] || SCENARIOS_START_DATA['happy'];

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
      const actionResponse = ACTIONS_DATA[action] || { status: "success" };

      if (action === 'pay_happy') {
        state.metrics.confirmed_count++;
        state.metrics.confirmed_today++;
        state.metrics.active_holds = Math.max(0, state.metrics.active_holds - 1);
        state.metrics.emails_sent += 2;
        logAudit('PAYMENT', 'Payment of ₹2,500 captured for ' + state.patient.first_name + '. Appointment confirmed.');
      } else if (action === 'reschedule_slot_lost') {
        const lateTask = state.tasks.find(t => t.id && t.id.includes('LATE'));
        if (lateTask) {
          lateTask.status = "RESOLVED";
          lateTask.resolved_at = new Date().toISOString();
          lateTask.resolution_notes = "Alternate priority slot SLOT-103 offered and accepted.";
        }
        state.metrics.p0_urgent_tasks = Math.max(0, state.metrics.p0_urgent_tasks - 1);
        logAudit('BOOKING', 'Patient Aarav rescheduled to alternate slot SLOT-103.');
      } else if (action === 'refund_slot_lost') {
        const lateTask = state.tasks.find(t => t.id && t.id.includes('LATE'));
        if (lateTask) {
          lateTask.status = "RESOLVED";
          lateTask.resolved_at = new Date().toISOString();
          lateTask.resolution_notes = "Full UPI refund of ₹2,500 issued.";
        }
        state.metrics.p0_urgent_tasks = Math.max(0, state.metrics.p0_urgent_tasks - 1);
        logAudit('PAYMENT', 'Full UPI refund of ₹2,500 processed for Aarav.');
      } else if (action === 'retry_booking') {
        const setmoreTask = state.tasks.find(t => t.id && t.id.includes('SETMORE'));
        if (setmoreTask) {
          setmoreTask.status = "RESOLVED";
          setmoreTask.resolved_at = new Date().toISOString();
          setmoreTask.resolution_notes = "Calendar sync successful on retry attempt 2.";
        }
        state.metrics.p0_urgent_tasks = Math.max(0, state.metrics.p0_urgent_tasks - 1);
        logAudit('BOOKING', 'Setmore calendar outage resolved. Appointment synched.');
      } else if (action === 'test_wrong_pin') {
        logAudit('SECURITY', 'PIN authentication failed for +91 98765 43210 (Attempt 1 of 3).');
      } else if (action === 'test_correct_pin') {
        logAudit('SECURITY', 'PIN 4321 verified. Discrete session unlocked for Pooja.');
      } else if (action === 'resolve_crisis') {
        const crisisTask = state.tasks.find(t => t.id && t.id.includes('CRISIS'));
        if (crisisTask) {
          crisisTask.status = "RESOLVED";
          crisisTask.resolved_at = new Date().toISOString();
          crisisTask.resolution_notes = "Duty psychiatrist Dr. Maya Nambiar reached patient via phone.";
        }
        state.metrics.p0_urgent_tasks = Math.max(0, state.metrics.p0_urgent_tasks - 1);
        logAudit('CRISIS', 'On-call psychiatrist connected with patient. AI bot unmuted.');
      } else if (action === 'verify_lab_otp') {
        logAudit('SECURITY', '2FA OTP verified. Secure medical vault opened.');
      }

      saveSharedState(state);

      return new Response(JSON.stringify(actionResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 9. POST /api/simulate/reset
    if (path === '/api/simulate/reset' && method === 'POST') {
      const freshState = createInitialState();
      Object.assign(state, freshState);
      saveSharedState(state);
      logAudit('SYSTEM', 'Simulation state reset to clean baseline.');

      return new Response(JSON.stringify({ status: "reset_complete" }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 10. POST /api/call/inbound
    if (path === '/api/call/inbound' && method === 'POST') {
      state.metrics.calls_count++;
      state.tasks.unshift({
        task_id: "TASK-CALL-" + Date.now().toString().slice(-4),
        id: "TASK-CALL-" + Date.now().toString().slice(-4),
        priority: "P1_HIGH",
        status: "OPEN",
        title: "P1 Missed Call Callback (30m SLA)",
        patient_name: "Inbound Caller",
        patient_phone_masked: "+91 98765 •••••",
        description: 'Missed call callback task for ' + (body.phone || '+91 98765 00123'),
        assigned_to: "Reception Frontdesk",
        due_date: new Date(Date.now() + 30 * 60000).toISOString(),
        is_overdue: false,
        time_left_seconds: 1800,
        resolved_at: null,
        resolution_notes: null
      });
      state.calls.unshift({
        status: "MISSED",
        caller_phone: body.phone || "+91 98765 00123",
        caller_phone_masked: "+91 98765 •••••",
        patient_name: "Inbound Caller",
        timestamp: new Date().toISOString(),
        duration_seconds: 0,
        agent_id: "Reception-IVR"
      });
      state.metrics.p1_high_tasks++;
      logAudit('TELEPHONY', 'Inbound missed call received. P1 30-minute callback task scheduled.');
      saveSharedState(state);

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
