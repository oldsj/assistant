/**
 * Twilio Function: Phone Number Allowlist
 *
 * This function runs on Twilio's serverless infrastructure and acts as the
 * first layer of security for incoming calls. Only approved phone numbers
 * can proceed to the voice assistant.
 *
 * Setup:
 * 1. In Twilio Console, go to Functions & Assets > Services
 * 2. Create a new Service (e.g., "voice-assistant-auth")
 * 3. Add this function with path: /incoming-call
 * 4. Deploy the service
 * 5. Configure your Twilio phone number webhook to point to this function
 *
 * How it works:
 * - Checks incoming caller's phone number against allowlist
 * - If allowed: redirects to your assistant server for processing
 * - If not allowed: immediately rejects the call
 */

exports.handler = (context, event, callback) => {
  // Prepare a new Voice TwiML object that will control Twilio's response
  // to the incoming call
  const twiml = new Twilio.twiml.VoiceResponse();

  // The incoming phone number is provided by Twilio as the `From` property
  const incomingNumber = event.From;

  // Get allowed numbers from environment variable
  // Set ALLOWED_NUMBERS in Twilio Function Environment Variables
  // Example: +15551234567,+15559876543,+15555551234
  const allowList = (context.ALLOWED_NUMBERS || "")
    .split(",")
    .map((n) => n.trim());

  // Get webhook URL from environment variable
  // Set WEBHOOK_URL in Twilio Function Environment Variables
  // Example: https://your-tunnel-name.trycloudflare.com/incoming-call
  const webhookUrl = context.WEBHOOK_URL;

  // Check if the incoming number is in the allow list
  const isAllowed = allowList.includes(incomingNumber);

  if (isAllowed) {
    // If the number is allowed, redirect call to the webhook that
    // handles allowed callers
    twiml.redirect(webhookUrl);
  } else {
    // Block all other numbers
    twiml.reject();
  }

  return callback(null, twiml);
};
