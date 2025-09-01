# Google Maps Lead Finder

A simple **client-side web application** that uses the **Google Maps Places API** to find local businesses.  
It helps freelancers, web developers, and marketing agencies identify potential clients by filtering for businesses that do not have a website listed on their Google Business Profile.

---

## Features

- **Lead Generation**: Find businesses in any location that are missing a website.
- **Simple Interface**: Clean, easy-to-use design built with Tailwind CSS.
- **Two Views**:
  - **Potential Leads** → Businesses without a website (name, phone, address).
  - **All Businesses Found** → Complete list showing which have websites and which do not.
- **Zero Backend**: Runs entirely in the browser.
- **Secure**: `.gitignore` keeps your API key out of the repository.

---

## Getting Started

### Prerequisites

- A modern web browser (Chrome, Firefox, Edge, etc.)
- A Google Cloud Platform account with an API key

### Step 1: Get a Google Maps API Key

1. Go to the **Google Cloud Console**.
2. Create a new project (or select an existing one).
3. Enable the **Places API**.
4. Go to **APIs & Services → Credentials**.
5. Click **Create Credentials → API Key**.
6. Copy the generated key.
7. *(Optional but recommended)* Restrict the key to HTTP referrers (e.g., `http://localhost` for testing).

> **Note:** Google requires billing, but includes **$200 monthly free credit**, which is enough for thousands of searches.

### Step 2: Set Up the Project

```bash
git clone https://github.com/your-username/google-maps-lead-finder.git
cd google-maps-lead-finder


- Rename config.js.example → config.js.

Add your API key inside:

// config.js
const API_KEY = "PASTE_YOUR_REAL_API_KEY_HERE";


(config.js is already in .gitignore, so it won’t be pushed to Git.)
```
### Step 3: Run the Application

Open index.html in your browser.

Enter a Business Type (e.g., Plumbers, Hair Salons).

Enter a Location (e.g., Miami, Florida, London).

Click Find Businesses.

Results will appear in two tables:

Potential Leads → Businesses without a website.

All Businesses Found → All results (with/without websites).

### Security

The API key is stored locally in config.js.

config.js is ignored by Git.

Never commit your API key to version control.