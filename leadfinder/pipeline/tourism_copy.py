"""Words for the Sri Lanka tourism preview sites.

House style: plain, specific, British spelling. No em or en dashes, no
emoji, no exclamation marks, no "nestled", "paradise", "hidden gem",
"breathtaking", "unforgettable" or "embark". Say what a guest does or gets.
Placeholders: {name} {town} {region} {beach} {category} {season}.
tests/test_tourism_sites.py checks every rendered page against these rules.
"""

from __future__ import annotations

BANNED = ("—", "–", "!", "nestled", "paradise", "hidden gem", "breathtaking", "unforgettable",
          "embark", "tapestry", "elevate", "seamless", "a must-visit", "look no further")

# tourism_category -> family (one look per family) and variant
FAMILY = {
    'Resorts & boutique hotels': 'stay',
    'Villas & holiday rentals': 'stay',
    'Guest houses & homestays': 'stay',
    'Wedding venues & photographers': 'stay',
    'Hostels & surf hostels': 'hostel',
    'Surf camps & surf schools': 'surf',
    'Surf shops & board rental': 'surf',
    'Cafés': 'cafe',
    'Coworking & coliving': 'cafe',
    'Restaurants & beach clubs': 'dine',
    'Yoga, Ayurveda & spas': 'well',
    'Whale watching, boat & lagoon tours': 'trip',
    'Safari jeep operators': 'trip',
    'Diving & snorkelling': 'trip',
    'Tea estate tours & trekking': 'trip',
    'Cooking classes & local experiences': 'trip',
    'Tour operators & travel agents': 'trip',
    'Scooter, tuk-tuk & airport transfers': 'ride',
    'Gem, jewellery & souvenir shops': 'local',
    'Tattoo, laundry & traveller services': 'local',
}

# Palettes per family. Several per family so neighbouring businesses differ.
# (paper, ink, accent, deep, soft)
PALETTES = {
    'stay': [('#eef1ec', '#17231e', '#2f5d50', '#1f3b33', '#c9d6cd'),
             ('#f1efe9', '#1d1f24', '#3b5a78', '#22344a', '#cfd8e0'),
             ('#eceee6', '#202018', '#6b6a2e', '#3c3b19', '#d8d9c4')],
    'hostel': [('#f4f7fb', '#1a1423', '#ff4f79', '#2a1f3d', '#8fd3ff'),
               ('#fbf8f2', '#14213d', '#ff7a1a', '#14213d', '#a6e3c8'),
               ('#f6f6f1', '#1b1b1b', '#3b5bfd', '#1b1b1b', '#ffd23f')],
    'surf': [('#f2f7f5', '#0c2a30', '#0b6b7a', '#073f48', '#f6b23c'),
             ('#f5f6f1', '#122326', '#1f7a5c', '#0e3d30', '#ff8a5b'),
             ('#eff5f8', '#10202b', '#2364aa', '#0f2f52', '#fec601')],
    'cafe': [('#f7f8f2', '#2a1d15', '#56703d', '#2a1d15', '#e4ead6'),
             ('#f8f6f3', '#251a17', '#8c3b2e', '#251a17', '#ecd9c6'),
             ('#f4f6f8', '#1c2229', '#2d5f73', '#1c2229', '#d8e6ec')],
    'dine': [('#0f1a24', '#efe6d6', '#f2a33a', '#091119', '#22313f'),
             ('#16161d', '#ece7df', '#d9b26f', '#0d0d12', '#26262f'),
             ('#0e1f1c', '#eae7dc', '#e3875b', '#08130f', '#1c302b')],
    'well': [('#e6ebe2', '#26302a', '#7a5c74', '#3a3f35', '#cfd8c8'),
             ('#ece9e4', '#2b2a2f', '#4f6f63', '#2b2a2f', '#d9d4cc'),
             ('#e9ecef', '#262b33', '#8a6a4a', '#262b33', '#d3dae2')],
    'trip': [('#f3f5f4', '#132028', '#0d5c8a', '#0b2e44', '#cfe3ee')],
    'ride': [('#f2f4f6', '#101820', '#ffc531', '#101820', '#dfe4ea'),
             ('#f4f4f1', '#161616', '#e4572e', '#161616', '#e3e3dc')],
    'local': [('#f6f6f4', '#1c1c22', '#5b4bb7', '#1c1c22', '#e2e0f0'),
              ('#f5f6f6', '#18201f', '#1f7a6d', '#18201f', '#d6e7e3')],
}
# Trips take their colour from what the trip is about.
TRIP_PALETTE = {
    'Whale watching, boat & lagoon tours': ('#f1f5f8', '#0d1f2d', '#1666a8', '#0b2a45', '#cfe1f0'),
    'Safari jeep operators': ('#f4f2ec', '#1f1b14', '#9a6a1f', '#3a2c12', '#e5dcc6'),
    'Diving & snorkelling': ('#eff7f7', '#0b2426', '#0e8a8a', '#074446', '#c9ecea'),
    'Tea estate tours & trekking': ('#eef2ea', '#18241a', '#3f7a3a', '#1c3a1f', '#d3e2cd'),
    'Cooking classes & local experiences': ('#f6f3ee', '#24180f', '#b5521f', '#3b200d', '#efdccb'),
    'Tour operators & travel agents': ('#f2f4f3', '#16222a', '#22705f', '#123a32', '#d2e4de'),
}

FONTS = {  # display face, body face, display weight
    'stay': ('cormorant', 'geist', 400),
    'hostel': ('archivo', 'geist', 800),
    'surf': ('archivo', 'geist', 800),
    'cafe': ('young-serif', 'geist', 400),
    'dine': ('bodoni', 'geist', 400),
    'well': ('cormorant', 'geist', 400),
    'trip': ('archivo', 'geist', 700),
    'ride': ('archivo', 'geist', 700),
    'local': ('young-serif', 'geist', 400),
}

# What the booking box asks for, per family.
BOOKING = {
    'stay': {'title': 'Check availability', 'button': 'Check availability',
             'fields': ['checkin', 'checkout', 'guests'], 'nav': 'Book'},
    'hostel': {'title': 'Grab a bed', 'button': 'Check beds', 'fields': ['checkin', 'checkout', 'beds'], 'nav': 'Book a bed'},
    'surf': {'title': 'Book a session', 'button': 'Book a lesson', 'fields': ['level', 'date', 'people'], 'nav': 'Book'},
    'cafe': {'title': 'Order ahead', 'button': 'Send my order', 'fields': ['time', 'note'], 'nav': 'Order ahead'},
    'dine': {'title': 'Reserve a table', 'button': 'Reserve a table', 'fields': ['date', 'time', 'guests'], 'nav': 'Reserve'},
    'well': {'title': 'Book a session', 'button': 'Book a session', 'fields': ['treatment', 'date', 'people'], 'nav': 'Book'},
    'trip': {'title': 'Pick a date', 'button': 'Check dates', 'fields': ['date', 'people'], 'nav': 'Book a trip'},
    'ride': {'title': 'Get a price', 'button': 'Get a price', 'fields': ['from', 'to', 'date', 'people'], 'nav': 'Get a price'},
    'local': {'title': 'Ask us anything', 'button': 'Send', 'fields': ['note'], 'nav': 'Contact'},
}

BOOKING_BY_CATEGORY = {
    'Surf shops & board rental': {'title': 'Rent a board', 'button': 'Reserve a board', 'fields': ['board', 'date', 'days'], 'nav': 'Rent a board'},
    'Coworking & coliving': {'title': 'Book a desk', 'button': 'Book a desk', 'fields': ['date', 'days'], 'nav': 'Book a desk'},
    'Wedding venues & photographers': {'title': 'Check your date', 'button': 'Check our availability', 'fields': ['date', 'guests'], 'nav': 'Your date'},
}

# Per category: nav labels, headlines (one is picked per business), intro,
# what they offer (title, line) and the special section.
CATEGORY = {
    'Resorts & boutique hotels': {
        'nav': ['Rooms', 'Around us', 'Location'],
        'headlines': ['Rooms, quiet and a slow breakfast in {town}', 'Stay in {town}, close to {beach}',
                      'A place to land in {town}'],
        'intro': ['{name} is a small hotel in {town}. Book with us directly and you deal with the people who run the place: '
                  'ask for a quieter room, an early breakfast before a train or a driver from the airport, and get an answer the same day.',
                  'Wake up in {town}, eat breakfast on the terrace and be at {beach} before the day warms up. '
                  '{name} keeps things simple: clean rooms, good food and help planning the rest of your trip.'],
        'offer': [('Rooms', 'Doubles, twins and family rooms. Tell us your dates and we send photos and the rate.'),
                  ('Breakfast', 'Sri Lankan or western, served when you want it, packed if you leave early.'),
                  ('Getting here', 'Airport pickups and drivers for day trips, booked by us at local prices.'),
                  ('Trips', 'Our own short list of what is worth your time around {town}.')],
        'special': 'stay',
    },
    'Villas & holiday rentals': {
        'nav': ['The villa', 'Around us', 'Location'],
        'headlines': ['The whole place to yourselves in {town}', 'A villa in {town} for slow days',
                      'Your own house near {beach}'],
        'intro': ['{name} is a private holiday house in {town}. Book directly for the best rate and talk to the host, '
                  'not a call centre: arrival times, a cook for the evening or a tuk-tuk to {beach} are one message away.',
                  'Rent all of {name} for a week, or a long weekend. Space to cook, read and sleep in, '
                  'and {town} close enough for dinner out when you feel like it.'],
        'offer': [('Sleeps', 'Bedrooms for families and friends travelling together. Ask for the floor plan.'),
                  ('Staff', 'Housekeeping every day and a cook on request.'),
                  ('Long stays', 'Weekly and monthly rates for remote workers and families.'),
                  ('Arrival', 'We arrange your airport pickup and stock the fridge before you arrive.')],
        'special': 'stay',
    },
    'Guest houses & homestays': {
        'nav': ['Rooms', 'Around us', 'Location'],
        'headlines': ['A family guest house in {town}', 'Stay with a local family in {town}',
                      'Clean rooms, home cooking, {town}'],
        'intro': ['{name} is a family-run guest house in {town}. You get a clean room, a proper rice and curry at night '
                  'and hosts who know which bus, which beach and which day the market is on.',
                  'Stay at {name} and see {town} the way people who live here do. Simple rooms, home cooking '
                  'and help with tuk-tuks, trains and day trips at local prices.'],
        'offer': [('Rooms', 'Double and family rooms with fans or air conditioning.'),
                  ('Home cooking', 'Breakfast every morning and rice and curry dinners on request.'),
                  ('Local help', 'Train times, drivers and day trips arranged by your hosts.'),
                  ('Longer stays', 'Ask about a better rate for a week or more.')],
        'special': 'stay',
    },
    'Wedding venues & photographers': {
        'nav': ['Weddings', 'Around us', 'Location'],
        'headlines': ['Weddings in {town}', 'Your wedding day, planned in {town}',
                      'Get married in {town}'],
        'intro': ['{name} plans and hosts weddings in {town}, for couples from Sri Lanka and from abroad. '
                  'Tell us your date and guest numbers and we send packages, photos of past days and an honest quote.',
                  'From the poruwa ceremony to the last dance, {name} looks after the details so your families can enjoy the day.'],
        'offer': [('Ceremony', 'Traditional poruwa, civil or blessing ceremonies.'),
                  ('Reception', 'Seated dinners and buffets for small and large guest lists.'),
                  ('Photography', 'Photos and film of the day, with an album to keep.'),
                  ('Guests from abroad', 'Rooms, transfers and trips for overseas guests.')],
        'special': 'stay',
    },
    'Hostels & surf hostels': {
        'nav': ['Beds', 'What is on', 'Nearby'],
        'headlines': ['Beds, boards and good people in {town}', 'Your base in {town}', 'Cheap beds, good nights, {town}'],
        'intro': ['{name} is a hostel in {town} for people travelling on their own or with friends. '
                  'Dorms and private rooms, a common area that fills up at sunset and staff who will tell you where to eat.',
                  'Stay at {name}, meet people at breakfast and go to {beach} together. Book your bed direct and pay the lowest rate.'],
        'offer': [('Dorms', 'Bunks with a light, a plug and a locker each.'),
                  ('Private rooms', 'For couples and anyone who wants a door that closes.'),
                  ('Social', 'Family dinners, sunset trips and a board for what is on this week.'),
                  ('Help desk', 'Buses, trains, scooters and day trips booked at the front desk.')],
        'special': 'hostel',
    },
    'Surf camps & surf schools': {
        'nav': ['Lessons', 'The break', 'Nearby'],
        'headlines': ['Learn to surf in {town}', 'Surf lessons at {beach}', 'Stand up, then go again'],
        'intro': ['{name} teaches surfing in {town}. Small groups, patient coaches and a board that suits your level. '
                  'Most people stand up in their first lesson.',
                  'From your first whitewater wave to your first green one, {name} takes you there at {beach}. '
                  'Lessons every morning and afternoon, boards and rash vests included.'],
        'offer': [('Beginner', 'Two hours in the whitewater: paddling, popping up and riding straight to the beach.'),
                  ('Improver', 'You can stand. Now catch unbroken waves, turn and read the line-up.'),
                  ('Guided sessions', 'For confident surfers: we take you to the right break for the day.'),
                  ('Surf camp', 'Lessons, video feedback, a bed and breakfast in one weekly price.')],
        'special': 'surf',
    },
    'Surf shops & board rental': {
        'nav': ['Boards', 'The break', 'Nearby'],
        'headlines': ['Boards for every wave in {town}', 'Rent, buy or fix a board in {town}', 'The right board for {beach}'],
        'intro': ['{name} rents and sells surfboards in {town}. Soft tops for your first week, hard boards when you are ready, '
                  'and repairs while you have a coffee.',
                  'Tell {name} your height, weight and how long you have surfed, and walk out with a board that works on {beach}.'],
        'offer': [('Rentals', 'By the hour, day or week. Soft tops, longboards and shortboards.'),
                  ('Ding repairs', 'Most repairs back the same or next day.'),
                  ('Wax, leashes, fins', 'Everything you forgot to pack.'),
                  ('Lessons', 'We can set you up with a coach for your first sessions.')],
        'special': 'surf',
    },
    'Cafés': {
        'nav': ['Menu', 'Hours', 'Find us'],
        'headlines': ['Coffee and breakfast in {town}', 'Good coffee, {town}', 'Breakfast until late in {town}'],
        'intro': ['{name} is a café in {town}. Proper coffee, breakfast you can surf on, fresh juice and a table in the shade for as long as you need it.',
                  'Come to {name} after {beach} for coffee, a bowl or a toastie, and stay for the Wi-Fi.'],
        'offer': [('Coffee', 'Espresso, flat whites, iced coffee and Ceylon tea.'),
                  ('Breakfast', 'Eggs, toast, pancakes and Sri Lankan hoppers.'),
                  ('Bowls and juice', 'Smoothie bowls, king coconut and fresh fruit juice.'),
                  ('Take away', 'Order ahead and pick up on your way to the beach.')],
        'special': 'menu',
    },
    'Coworking & coliving': {
        'nav': ['Desks', 'Hours', 'Find us'],
        'headlines': ['Work near the waves in {town}', 'Desks, fast Wi-Fi and coffee in {town}', 'Work in the morning, surf at four'],
        'intro': ['{name} gives remote workers in {town} a desk, fast fibre with a backup line and quiet rooms for calls.',
                  'Join {name} for a day, a week or a month and work next to people who also came to {town} for the sea.'],
        'offer': [('Day pass', 'A desk, Wi-Fi and coffee for the day.'),
                  ('Monthly', 'Your own desk, a locker and 24 hour access.'),
                  ('Call rooms', 'Quiet booths for calls and meetings.'),
                  ('Community', 'Weekly dinners, surf trips and talks.')],
        'special': 'menu',
    },
    'Restaurants & beach clubs': {
        'nav': ['Menu', 'Reserve', 'Find us'],
        'headlines': ['Dinner in {town}', 'Fresh fish and cold drinks in {town}', 'Stay for sunset in {town}'],
        'intro': ['{name} serves lunch and dinner in {town}. Fish from the morning boats, curries cooked the slow way and cold drinks when the sun goes down.',
                  'Book a table at {name} for sunset and stay for dinner. Sri Lankan and seafood dishes, cooked to order.'],
        'intro_inland': ['{name} serves lunch and dinner in {town}. Curries cooked the slow way, kottu off the griddle and cold drinks after a long day out.',
                         'Book a table at {name} after a day of sightseeing around {town}. Sri Lankan dishes, cooked to order and served generously.'],
        'offer_inland': [('Rice and curry', 'Five or more curries with rice, papadam and sambol.'),
                         ('Kottu and hoppers', 'Made to order at night, the way locals eat them.'),
                         ('Drinks', 'Fresh juice, Lion lager, arrack cocktails and mocktails.'),
                         ('Groups', 'Tour groups, family dinners and private bookings.')],
        'offer': [('Seafood', 'The day\'s catch grilled, devilled or in a curry.'),
                  ('Rice and curry', 'Five or more curries with rice, papadam and sambol.'),
                  ('Drinks', 'Fresh juice, Lion lager, arrack cocktails and mocktails.'),
                  ('Groups', 'Birthdays, family dinners and private bookings.')],
        'special': 'menu',
    },
    'Yoga, Ayurveda & spas': {
        'nav': ['Treatments', 'Hours', 'Find us'],
        'headlines': ['Yoga and Ayurveda in {town}', 'Rest properly in {town}', 'Treatments and classes in {town}'],
        'intro': ['{name} offers yoga, massage and Ayurvedic treatments in {town}. Come for an hour after surfing, or for a week to recover properly.',
                  'At {name} trained therapists use oils prepared the traditional way. Book a single treatment or a programme planned around you.'],
        'offer': [('Yoga', 'Morning and sunset classes for beginners and regular students.'),
                  ('Ayurvedic massage', 'Full body abhyanga with warm herbal oils.'),
                  ('Shirodhara', 'A steady stream of warm oil across the forehead to calm the mind.'),
                  ('Programmes', 'Three to fourteen days, planned after a consultation.')],
        'special': 'well',
    },
    'Whale watching, boat & lagoon tours': {
        'nav': ['The trip', 'When to go', 'Book'],
        'headlines': ['Whales, dolphins and the open sea from {town}', 'Out on the water from {town}', 'Boat trips from {town}'],
        'intro': ['{name} takes small groups out on the water from {town}. Licensed boats, life jackets for everyone and a crew that has done this for years.',
                  'Book with {name} and you head out early, with breakfast on board and a crew who know where to look.'],
        'itinerary': [('6:00', 'Meet at the harbour, safety briefing and life jackets.'),
                      ('6:30', 'Head out with breakfast, tea and fruit on board.'),
                      ('8:00', 'Time with the whales, dolphins or lagoon wildlife, at a respectful distance.'),
                      ('11:00', 'Back at the harbour. Hotel drop off on request.')],
        'included': ['Licensed boat and crew', 'Life jackets', 'Breakfast and water', 'Hotel pickup on request'],
        'special': 'trip',
    },
    'Safari jeep operators': {
        'nav': ['The safari', 'When to go', 'Book'],
        'headlines': ['Leopards, elephants and early starts', 'Jeep safaris from {town}', 'Into the park at first light'],
        'intro': ['{name} runs jeep safaris from {town}. Open jeeps, experienced trackers and park tickets sorted for you.',
                  'Go with {name} at dawn when the animals are moving. Half day and full day safaris, picked up from your hotel.'],
        'itinerary': [('5:00', 'Pickup from your hotel in an open jeep.'),
                      ('6:00', 'Through the gate as the park opens.'),
                      ('9:00', 'Breakfast stop at a picnic spot inside the park.'),
                      ('11:30', 'Back at your hotel. Afternoon safaris also available.')],
        'included': ['Open safari jeep and driver', 'Tracker and park ticket help', 'Water and breakfast box', 'Hotel pickup'],
        'special': 'trip',
    },
    'Diving & snorkelling': {
        'nav': ['Dives', 'When to go', 'Book'],
        'headlines': ['Dive and snorkel from {town}', 'Reefs and wrecks off {town}', 'Under the water at {town}'],
        'intro': ['{name} runs dives and snorkel trips from {town}. Courses for first timers and guided dives for certified divers.',
                  'See turtles, reef fish and wrecks with {name}. Small groups, serviced equipment and careful briefings.'],
        'itinerary': [('8:00', 'Meet at the dive centre, kit fitting and briefing.'),
                      ('8:45', 'Boat out to the first site.'),
                      ('9:15', 'First dive or snorkel, about 45 minutes.'),
                      ('11:30', 'Second site, then back to shore.')],
        'included': ['All equipment', 'Boat and guide', 'Water and fruit', 'Certification on courses'],
        'special': 'trip',
    },
    'Tea estate tours & trekking': {
        'nav': ['The walk', 'When to go', 'Book'],
        'headlines': ['Walk the tea country from {town}', 'Tea estates and ridge walks', 'Hill walks and tea from {town}'],
        'intro': ['{name} leads walks and tea estate visits around {town}. See how tea is picked and made, then walk the ridges above the valley.',
                  'Go with {name} on foot through estates, villages and cloud forest, with a guide who grew up here.'],
        'itinerary': [('7:00', 'Meet in {town}, tea and a short briefing.'),
                      ('7:30', 'Walk through the estate with the pluckers at work.'),
                      ('10:00', 'Factory visit and tasting.'),
                      ('12:30', 'Lunch with a view, then back to town.')],
        'included': ['Local guide', 'Tea tasting', 'Lunch and water', 'Transport to the start'],
        'special': 'trip',
    },
    'Cooking classes & local experiences': {
        'nav': ['The class', 'When to go', 'Book'],
        'headlines': ['Cook Sri Lankan food in {town}', 'A morning in a {town} kitchen', 'Learn the curries, take the recipes home'],
        'intro': ['{name} teaches Sri Lankan cooking in {town}. Shop at the market, grate your own coconut and cook five curries to eat together.',
                  'Join {name} for a few hours of local life in {town}: the market, the kitchen and a long lunch.'],
        'itinerary': [('9:00', 'Meet at the market and choose vegetables and spices.'),
                      ('10:00', 'In the kitchen: coconut, spice blends and curries.'),
                      ('12:30', 'Sit down and eat what you cooked.'),
                      ('13:30', 'Recipes to take home.')],
        'included': ['Market visit', 'All ingredients', 'Lunch', 'Printed recipes'],
        'special': 'trip',
    },
    'Tour operators & travel agents': {
        'nav': ['Trips', 'When to go', 'Plan'],
        'headlines': ['Sri Lanka, planned with someone who lives here', 'Round trips and day tours from {town}',
                      'Your Sri Lanka trip, planned in {town}'],
        'intro': ['{name} plans trips around Sri Lanka from {town}: a driver for the week, day tours or a full itinerary with hotels.',
                  'Tell {name} how many days you have and what you like. We send back a route, a price and the car that suits your group.'],
        'itinerary': [('Day 1', 'Airport pickup and a night by the coast.'),
                      ('Day 2 to 4', 'The Cultural Triangle: Sigiriya, Dambulla and Polonnaruwa.'),
                      ('Day 5 to 7', 'Kandy, then the train through the tea country to Ella.'),
                      ('Day 8 to 10', 'Safari, then the south coast beaches.')],
        'included': ['Private car and driver', 'Hotels that suit your budget', 'Entrance tickets on request', 'Help 24 hours a day'],
        'special': 'trip',
    },
    'Scooter, tuk-tuk & airport transfers': {
        'nav': ['Rides', 'Rates', 'Book'],
        'headlines': ['Airport pickups and rides from {town}', 'Get around {town} your way', 'From the airport to {town}, sorted'],
        'intro': ['{name} drives and rents in {town}: airport transfers, tuk-tuks, scooters and cars with a driver for the day.',
                  'Book {name} before you land and someone with your name on a sign is waiting at arrivals.'],
        'offer': [('Airport transfers', 'Pickup at Bandaranaike Airport, any time of day or night.'),
                  ('Tuk-tuk hire', 'Drive yourself with a tourist permit, or hire one with a driver.'),
                  ('Scooters', 'By the day or week, helmets included.'),
                  ('Car and driver', 'Day trips and round trips across the island.')],
        'special': 'ride',
    },
    'Gem, jewellery & souvenir shops': {
        'nav': ['The shop', 'Hours', 'Find us'],
        'headlines': ['Sri Lankan gems and jewellery in {town}', 'Moonstones, sapphires and gifts in {town}',
                      'Handmade in Sri Lanka, sold in {town}'],
        'intro': ['{name} sells gems, jewellery and gifts in {town}. Every stone comes with honest information about what it is and where it came from.',
                  'Visit {name} in {town} for sapphires, moonstones and handmade pieces, set while you wait or sent home.'],
        'offer': [('Gems', 'Sapphires, moonstones and garnets, with certificates on request.'),
                  ('Jewellery', 'Rings, pendants and earrings made in our workshop.'),
                  ('Custom work', 'Bring a design and we make it.'),
                  ('Shipping', 'We post your purchase home, insured.')],
        'special': 'local',
    },
    'Tattoo, laundry & traveller services': {
        'nav': ['Services', 'Hours', 'Find us'],
        'headlines': ['{category} in {town}', 'Sorted in {town}', 'Here when you need us in {town}'],
        'intro': ['{name} looks after travellers and locals in {town}. Drop in, or message ahead and we will be ready for you.',
                  'Visit {name} in {town}. Fair prices, clear times and people who answer their phone.'],
        'offer': [('Walk-ins', 'Come by during opening hours.'),
                  ('Bookings', 'Message ahead for a set time.'),
                  ('Fair prices', 'Prices agreed before we start.'),
                  ('Local tips', 'Ask us anything about {town}.')],
        'special': 'local',
    },
}

# When to go, by area. Picked from the business's search town.
SEASONS = {
    'South Coast': ('November to April', 'The south and west coasts are calm and dry from November to April. '
                    'From May the south-west monsoon brings bigger swell and afternoon showers.'),
    'West Coast': ('November to April', 'Dry and calm from November to April. May to October brings the monsoon, rain and rough seas.'),
    'East Coast': ('May to September', 'The east coast has its season while the south gets the monsoon: '
                   'dry, calm and warm from May to September.'),
    'Hill Country': ('January to April', 'Cool all year. January to April is driest, with clear mornings on the ridges and in the tea.'),
    'Cultural Triangle': ('January to September', 'Dry for most of the year. October to December is the wettest time.'),
    'Safari': ('February to July', 'Best from February to July when water holes shrink and animals gather. '
               'Yala closes for part of September and October.'),
    'Rainforest': ('January to April', 'Rain falls all year in the forest. January to April is driest.'),
    'North': ('January to September', 'Hot and dry from January to September. October to December is the rainy season.'),
    'Colombo': ('December to March', 'Warm all year. December to March is driest.'),
}
SPECIAL_SEASONS = {
    'whale_south': 'Blue whales pass off Mirissa from December to April, most often in the morning when the sea is flat.',
    'whale_east': 'Off Trincomalee, blue and sperm whales are seen from March to August.',
    'whale_kalpitiya': 'Spinner dolphins gather off Kalpitiya in hundreds from November to April.',
    'surf_east': 'Arugam Bay has its waves from May to October, when the south coast is out of season.',
    'lagoon': 'River and lagoon trips run all year. Go early, when the water is still and the birds are feeding.',
    'surf_south': 'The south coast breaks are at their best from November to April.',
}

AIRPORT = (7.1808, 79.8841)  # Bandaranaike International, Katunayake
