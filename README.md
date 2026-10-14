# Table & Thyme — Local Restaurant Reservation System

A complete, local-first restaurant reservation demo built with Python, Flask, SQLite, HTML, CSS and JavaScript.

## Features
- Customer registration, login, profile and reservation history
- Reservation booking with date/time, party size and automatic table assignment
- Availability checks that reject overlapping bookings
- Booking reference codes and cancellation
- Loyalty account with points, tiers and reward redemption
- Admin dashboard with booking, occupancy and customer summaries
- Admin reservation management and status updates
- Table management
- Customer directory and loyalty overview
- SQL schema and demo data
- Local SQLite database persisted in `restaurant.db`

## Requirements
- Python 3.10 or newer
- Internet is only needed once to install Flask if it is not already installed. The app itself runs locally.

## Run on Windows
1. Extract the ZIP.
2. Open Command Prompt or PowerShell in the extracted `restaurant-reservation-system` folder.
3. Create a virtual environment (recommended):

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```

4. Install dependencies:

   ```bat
   pip install -r requirements.txt
   ```

5. Start the app:

   ```bat
   python app.py
   ```

6. Open `http://127.0.0.1:5000` in your browser.

## Demo accounts
- Admin: `admin` / `Admin@123`
- Customer: `ad.demo@example.com` / `Customer@123`

You can register another customer from the app.

## Database
The database is created automatically on first launch. Tables include:
- `users`
- `restaurant_tables`
- `reservations`
- `loyalty_accounts`
- `loyalty_transactions`
- `rewards`
- `reward_redemptions`
- `reservation_history`

To reset the demo database, stop the server and delete `restaurant.db`. It will be recreated with demo data on the next launch.

## Notes
- This is a local educational/demo application. It is not hardened for public internet deployment.
- Reservation times are demo slots in 30-minute increments from 11:00 to 21:00. Reservations are 90 minutes long.
- A table cannot have overlapping active reservations.
