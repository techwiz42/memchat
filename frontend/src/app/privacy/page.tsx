import Link from "next/link";

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        <Link
          href="/login"
          className="text-sm text-blue-600 hover:underline mb-6 inline-block"
        >
          &larr; Back to Sign In
        </Link>

        <div className="bg-white rounded-2xl shadow-lg p-8">
          <h1 className="text-2xl font-bold mb-6">Privacy Policy</h1>
          <p className="text-sm text-gray-500 mb-8">
            Last updated: February 27, 2026
          </p>

          <div className="space-y-6 text-sm text-gray-700 leading-relaxed">
            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                1. Data We Collect
              </h2>
              <p className="mb-2">
                When you use Memchat, we collect the following information:
              </p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Account information:</strong> email address and
                  hashed password, or Google account profile information if
                  you sign in with Google.
                </li>
                <li>
                  <strong>Conversation history:</strong> text messages you
                  exchange with the AI assistant.
                </li>
                <li>
                  <strong>Uploaded documents:</strong> files you upload for
                  use in conversations.
                </li>
                <li>
                  <strong>Voice transcripts:</strong> transcriptions of voice
                  interactions conducted through the app.
                </li>
                <li>
                  <strong>Extracted memories:</strong> significant facts and
                  details automatically identified from your conversations
                  (e.g. preferences, project context, personal details you
                  share).
                </li>
              </ul>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                2. How We Use Your Data
              </h2>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Automatic memory extraction:</strong> Memchat
                  automatically extracts and remembers significant information
                  from your conversations — facts, preferences, and details you
                  share. These memories are private to your account and used to
                  provide personalized, context-aware responses.
                </li>
                <li>
                  <strong>Memory management:</strong> you can view, search, and
                  delete individual memories on the Memories page at any time.
                </li>
                <li>
                  <strong>LLM processing:</strong> your messages are sent to
                  OpenAI&apos;s API for generating AI responses and extracting
                  memories. OpenAI&apos;s data usage policies apply to data sent
                  to their API.
                </li>
                <li>
                  We do not sell your personal data to third parties.
                </li>
              </ul>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                3. Data Storage
              </h2>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Database:</strong> account data, conversations, and
                  vector embeddings are stored in PostgreSQL with the pgvector
                  extension.
                </li>
                <li>
                  <strong>Sessions:</strong> session data is stored in Redis
                  and expires automatically.
                </li>
                <li>
                  All data is stored on servers hosted by DigitalOcean in the
                  United States.
                </li>
              </ul>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                4. Third-Party Services
              </h2>
              <p className="mb-2">
                Memchat integrates with the following third-party services:
              </p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>OpenAI API:</strong> for generating AI responses.
                  Your messages are sent to OpenAI for processing.
                </li>
                <li>
                  <strong>Omnia / Ultravox:</strong> for real-time voice
                  interactions via WebRTC.
                </li>
                <li>
                  <strong>Google OAuth:</strong> for optional sign-in via your
                  Google account.
                </li>
              </ul>
              <p className="mt-2">
                Each third-party service is governed by its own privacy policy.
                We encourage you to review their policies.
              </p>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                5. Your Rights
              </h2>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Data deletion:</strong> you may request deletion of
                  your account and all associated data at any time by
                  contacting us.
                </li>
                <li>
                  <strong>Data export:</strong> you may request an export of
                  your conversation history and account data.
                </li>
                <li>
                  <strong>Correction:</strong> you may request correction of
                  any inaccurate personal data.
                </li>
              </ul>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                6. Contact
              </h2>
              <p>
                For privacy-related questions or requests, contact us at{" "}
                <a
                  href="mailto:privacy@cyberiad.ai"
                  className="text-blue-600 hover:underline"
                >
                  privacy@cyberiad.ai
                </a>
                .
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
