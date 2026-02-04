# SeenIt Authentication Backend

Simple authentication server for the SeenIt Chrome Extension.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Start the server:
```bash
npm start
```

For development with auto-reload:
```bash
npm run dev
```

The server will run on `http://localhost:3000` by default.

## Storage (online DB vs local fallback)

This backend supports two storage modes:

- **MongoDB (recommended / “online database”)**: set `MONGODB_URI` (e.g. MongoDB Atlas) and users will be stored in the `users` collection with a unique index on `email`.
- **Local file fallback (dev-only)**: if `MONGODB_URI` is not set (or MongoDB connection fails), users are stored in `users.json`.

### MongoDB Atlas example

```bash
export MONGODB_URI="mongodb+srv://USER:PASS@CLUSTER/DBNAME?retryWrites=true&w=majority"
npm start
```

## API Endpoints

### POST /api/register
Register a new user.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "User registered successfully",
  "user": {
    "id": "1234567890",
    "email": "user@example.com"
  }
}
```

### POST /api/login
Login with email and password.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "user": {
    "id": "1234567890",
    "email": "user@example.com"
  }
}
```

### GET /api/health
Health check endpoint.

## Data Storage

User data is stored in MongoDB (if `MONGODB_URI` is set) or in `users.json` as a fallback. Passwords are hashed using bcrypt before storage.

## Security Notes

- Passwords are hashed with bcrypt (10 salt rounds)
- Email addresses are stored in lowercase
- Basic email format validation is performed
- Minimum password length: 6 characters

## How the extension uses this backend

- The extension calls this API from `extension/popup.js` (`API_BASE_URL = http://localhost:3000/api`).
- On successful login, the extension stores `{ id, email }` in `chrome.storage.local` under the key `user`.
- The rest of the popup UI is shown/hidden based on whether `user` exists in storage.
