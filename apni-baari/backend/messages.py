"""
Message templates, keyed by language code. Add more languages by adding a
new dict entry -- nothing else in the codebase needs to change.
"""

EN = {
    "welcome": "Welcome to Apni Baari 🌾\n\nWhat would you like to do?",
    "not_registered": (
        "This WhatsApp number is not linked to a registered farmer account.\n\n"
        "Please register first on the Apni Baari portal, then message us again."
    ),
    "ask_mobile": "Please enter your registered mobile number.",
    "mobile_not_found": "We couldn't find a farmer registered with that mobile number. Please register on the portal first.",
    "otp_sent": "An OTP has been sent to your registered mobile number. Please enter the 6-digit OTP.",
    "otp_verified": "OTP verified successfully ✅",
    "otp_invalid": "{error} Please try again.",
    "otp_expired": "Your OTP has expired. Reply 'resend' to get a new one.",
    "otp_too_many": "Too many incorrect attempts. Reply 'resend' to request a new OTP.",
    "otp_rate_limited": "{error}",
    "greeting_authenticated": "Welcome, {name} 🌾\n\nWhat would you like to do?",
    "unknown_input": "I didn't understand that.\n\nPlease choose an option from the menu.",
    "select_centre": "Select your procurement centre.",
    "select_crop": "Select your crop.",
    "select_date": "Select a procurement date.",
    "select_slot": "Available slots for {date}:\n{slots}\nPlease select one.",
    "no_slots": "No available slots for {date} at this centre. Please choose another date.",
    "confirm_booking": (
        "Please confirm your booking:\n\n"
        "Farmer: {name}\nProcurement Centre: {centre}\nCrop: {crop}\n"
        "Date: {date}\nTime: {time}\n\nReply CONFIRM to book or CANCEL to go back."
    ),
    "booking_success": (
        "🎉 Slot booked successfully!\n\n"
        "Booking ID: {booking_id}\nFarmer: {name}\nCentre: {centre}\n"
        "Date: {date}\nTime: {time}\n\n"
        "Please arrive at the procurement centre during your assigned slot.\n"
        "Thank you for using Apni Baari 🌾"
    ),
    "slot_full": "Sorry, this slot is full ❌\n\nPlease choose another available slot.",
    "slot_just_taken": "Sorry, this slot was just booked by another farmer. Please select another slot.",
    "duplicate_booking": "You already have a booking for this date:\n{summary}",
    "no_active_booking": "You don't have an active booking right now.",
    "my_booking": (
        "Your current booking:\n\n"
        "Booking ID: {booking_id}\nCentre: {centre}\nCrop: {crop}\n"
        "Date: {date}\nTime: {time}\nStatus: {status}\nQueue Position: {queue_position}"
    ),
    "available_slots_header": "Available slots:\n",
    "confirm_cancel": "Are you sure you want to cancel booking {booking_id}?",
    "cancelled": "Your booking {booking_id} has been cancelled.",
    "cancel_aborted": "Okay, your booking was kept.",
    "reschedule_pick_date": "Select a new date for your booking {booking_id}.",
    "reschedule_done": "Your booking has been rescheduled.\n\n" + "Booking ID: {booking_id}\nNew Date: {date}\nNew Time: {time}",
    "session_expired": "Your session has expired for security. Please start again by saying 'Hi'.",
    "help": (
        "I can help you:\n"
        "1. Book a procurement slot\n"
        "2. Check my booking\n"
        "3. Check available slots\n"
        "4. Cancel/reschedule a booking\n"
        "5. Get help\n\n"
        "Type Hi or Menu anytime to see this again."
    ),
}

HI = {
    "welcome": "अपनी बारी 🌾 में आपका स्वागत है\n\nआप क्या करना चाहेंगे?",
    "not_registered": (
        "यह व्हाट्सएप नंबर किसी पंजीकृत किसान खाते से जुड़ा नहीं है।\n\n"
        "कृपया पहले अपनी बारी पोर्टल पर पंजीकरण करें, फिर हमें दोबारा संदेश भेजें।"
    ),
    "ask_mobile": "कृपया अपना पंजीकृत मोबाइल नंबर दर्ज करें।",
    "mobile_not_found": "इस मोबाइल नंबर से पंजीकृत कोई किसान नहीं मिला। कृपया पहले पोर्टल पर पंजीकरण करें।",
    "otp_sent": "आपके पंजीकृत मोबाइल नंबर पर OTP भेजा गया है। कृपया 6 अंकों का OTP दर्ज करें।",
    "otp_verified": "OTP सफलतापूर्वक सत्यापित ✅",
    "otp_invalid": "{error} कृपया पुनः प्रयास करें।",
    "otp_expired": "आपका OTP समाप्त हो गया है। नया OTP पाने के लिए 'resend' लिखें।",
    "otp_too_many": "बहुत अधिक गलत प्रयास। नया OTP पाने के लिए 'resend' लिखें।",
    "otp_rate_limited": "{error}",
    "greeting_authenticated": "स्वागत है, {name} 🌾\n\nआप क्या करना चाहेंगे?",
    "unknown_input": "मुझे समझ नहीं आया।\n\nकृपया मेनू में से कोई विकल्प चुनें।",
    "select_centre": "अपना उपार्जन केंद्र चुनें।",
    "select_crop": "अपनी फसल चुनें।",
    "select_date": "उपार्जन की तारीख चुनें।",
    "select_slot": "{date} के लिए उपलब्ध स्लॉट:\n{slots}\nकृपया एक चुनें।",
    "no_slots": "इस केंद्र पर {date} के लिए कोई स्लॉट उपलब्ध नहीं है। कृपया अन्य तारीख चुनें।",
    "confirm_booking": (
        "कृपया अपनी बुकिंग की पुष्टि करें:\n\n"
        "किसान: {name}\nउपार्जन केंद्र: {centre}\nफसल: {crop}\n"
        "तारीख: {date}\nसमय: {time}\n\nबुक करने के लिए CONFIRM या वापस जाने के लिए CANCEL लिखें।"
    ),
    "booking_success": (
        "🎉 स्लॉट सफलतापूर्वक बुक हो गया!\n\n"
        "बुकिंग आईडी: {booking_id}\nकिसान: {name}\nकेंद्र: {centre}\n"
        "तारीख: {date}\nसमय: {time}\n\n"
        "कृपया अपने निर्धारित समय पर उपार्जन केंद्र पर पहुंचें।\n"
        "अपनी बारी का उपयोग करने के लिए धन्यवाद 🌾"
    ),
    "slot_full": "क्षमा करें, यह स्लॉट भर चुका है ❌\n\nकृपया कोई अन्य उपलब्ध स्लॉट चुनें।",
    "slot_just_taken": "क्षमा करें, यह स्लॉट अभी किसी अन्य किसान द्वारा बुक कर लिया गया। कृपया कोई अन्य स्लॉट चुनें।",
    "duplicate_booking": "इस तारीख के लिए आपकी पहले से ही बुकिंग है:\n{summary}",
    "no_active_booking": "अभी आपकी कोई सक्रिय बुकिंग नहीं है।",
    "my_booking": (
        "आपकी वर्तमान बुकिंग:\n\n"
        "बुकिंग आईडी: {booking_id}\nकेंद्र: {centre}\nफसल: {crop}\n"
        "तारीख: {date}\nसमय: {time}\nस्थिति: {status}\nकतार स्थिति: {queue_position}"
    ),
    "available_slots_header": "उपलब्ध स्लॉट:\n",
    "confirm_cancel": "क्या आप वाकई बुकिंग {booking_id} रद्द करना चाहते हैं?",
    "cancelled": "आपकी बुकिंग {booking_id} रद्द कर दी गई है।",
    "cancel_aborted": "ठीक है, आपकी बुकिंग बनी रहेगी।",
    "reschedule_pick_date": "अपनी बुकिंग {booking_id} के लिए नई तारीख चुनें।",
    "reschedule_done": "आपकी बुकिंग पुनर्निर्धारित कर दी गई है।\n\nबुकिंग आईडी: {booking_id}\nनई तारीख: {date}\nनया समय: {time}",
    "session_expired": "सुरक्षा कारणों से आपका सत्र समाप्त हो गया है। 'Hi' लिखकर फिर से शुरू करें।",
    "help": (
        "मैं आपकी मदद कर सकता हूँ:\n"
        "1. उपार्जन स्लॉट बुक करें\n"
        "2. मेरी बुकिंग देखें\n"
        "3. उपलब्ध स्लॉट देखें\n"
        "4. बुकिंग रद्द/पुनर्निर्धारित करें\n"
        "5. सहायता\n\n"
        "यह मेनू फिर से देखने के लिए कभी भी Hi या Menu लिखें।"
    ),
}

LANGUAGES = {"en": EN, "hi": HI}


def t(key: str, lang: str = "en", **kwargs) -> str:
    table = LANGUAGES.get(lang, EN)
    template = table.get(key, EN.get(key, key))
    return template.format(**kwargs) if kwargs else template
