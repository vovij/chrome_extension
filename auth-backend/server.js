const express = require('express');
const bcrypt = require('bcrypt');
const cors = require('cors');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const { MongoClient } = require('mongodb');

const app = express();
const PORT = process.env.PORT || 3000;
const DATA_FILE = path.join(__dirname, 'users.json');
const MONGODB_URI = process.env.MONGODB_URI;

let mongoClient = null;
let usersCollection = null;

// Middleware
app.use(cors());
app.use(bodyParser.json());

async function initMongoIfConfigured() {
  if (!MONGODB_URI) return;

  mongoClient = new MongoClient(MONGODB_URI);
  await mongoClient.connect();

  const db = mongoClient.db(); // uses DB from URI if present
  usersCollection = db.collection('users');

  // Ensure uniqueness by email
  await usersCollection.createIndex({ email: 1 }, { unique: true });

  console.log('Connected to MongoDB (online DB).');
}

function ensureLocalFile() {
  if (!fs.existsSync(DATA_FILE)) {
    fs.writeFileSync(DATA_FILE, JSON.stringify([]));
  }
}

function readUsersLocal() {
  ensureLocalFile();
  try {
    const data = fs.readFileSync(DATA_FILE, 'utf8');
    return JSON.parse(data);
  } catch (error) {
    return [];
  }
}

function writeUsersLocal(users) {
  ensureLocalFile();
  fs.writeFileSync(DATA_FILE, JSON.stringify(users, null, 2));
}

async function findUserByEmail(emailLower) {
  if (usersCollection) {
    return await usersCollection.findOne({ email: emailLower });
  }
  const users = readUsersLocal();
  return users.find(u => u.email === emailLower) || null;
}

async function insertUser(userDoc) {
  if (usersCollection) {
    const result = await usersCollection.insertOne(userDoc);
    return { ...userDoc, _id: result.insertedId };
  }
  const users = readUsersLocal();
  users.push(userDoc);
  writeUsersLocal(users);
  return userDoc;
}

// Register endpoint
app.post('/api/register', async (req, res) => {
  try {
    const { email, password } = req.body;

    // Validation
    if (!email || !password) {
      return res.status(400).json({ 
        success: false, 
        message: 'Email and password are required' 
      });
    }

    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      return res.status(400).json({ 
        success: false, 
        message: 'Invalid email format' 
      });
    }

    // Check password length
    if (password.length < 6) {
      return res.status(400).json({ 
        success: false, 
        message: 'Password must be at least 6 characters' 
      });
    }

    const emailLower = email.toLowerCase();

    // Check if user already exists
    const existing = await findUserByEmail(emailLower);
    if (existing) {
      return res.status(400).json({ 
        success: false, 
        message: 'User with this email already exists' 
      });
    }

    // Hash password with bcrypt (basic encryption)
    const saltRounds = 10;
    const hashedPassword = await bcrypt.hash(password, saltRounds);

    // Create new user
    const newUser = {
      id: Date.now().toString(),
      email: emailLower,
      password: hashedPassword,
      createdAt: new Date().toISOString()
    };

    // Save user
    await insertUser(newUser);

    res.status(201).json({ 
      success: true, 
      message: 'User registered successfully',
      user: {
        id: newUser.id,
        email: newUser.email
      }
    });
  } catch (error) {
    console.error('Registration error:', error);
    if (String(error && error.code) === '11000') {
      return res.status(400).json({
        success: false,
        message: 'User with this email already exists'
      });
    }
    res.status(500).json({ 
      success: false, 
      message: 'Internal server error' 
    });
  }
});

// Login endpoint
app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    // Validation
    if (!email || !password) {
      return res.status(400).json({ 
        success: false, 
        message: 'Email and password are required' 
      });
    }

    // Find user by email
    const emailLower = email.toLowerCase();
    const user = await findUserByEmail(emailLower);

    if (!user) {
      return res.status(401).json({ 
        success: false, 
        message: 'Invalid email or password' 
      });
    }

    // Verify password
    const passwordMatch = await bcrypt.compare(password, user.password);

    if (!passwordMatch) {
      return res.status(401).json({ 
        success: false, 
        message: 'Invalid email or password' 
      });
    }

    // Successful login
    res.json({ 
      success: true, 
      message: 'Login successful',
      user: {
        id: user.id,
        email: user.email
      }
    });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ 
      success: false, 
      message: 'Internal server error' 
    });
  }
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({
    success: true,
    message: 'Server is running',
    storage: usersCollection ? 'mongodb' : 'file'
  });
});

// Start server
async function start() {
  try {
    await initMongoIfConfigured();
  } catch (err) {
    console.error('Failed to connect to MongoDB. Falling back to local file.', err);
    usersCollection = null;
    if (mongoClient) {
      try { await mongoClient.close(); } catch {}
    }
    mongoClient = null;
  }

  if (!usersCollection) {
    ensureLocalFile();
  }

  app.listen(PORT, () => {
    console.log(`Authentication server running on http://localhost:${PORT}`);
    console.log(`Storage: ${usersCollection ? 'MongoDB' : `Local file (${DATA_FILE})`}`);
  });
}

start();
