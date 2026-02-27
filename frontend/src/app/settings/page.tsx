"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { isLoggedIn } from "@/lib/auth";
import { apiFetch } from "@/lib/api";

interface Settings {
  agent_name: string;
  omnia_voice_name: string;
  omnia_language_code: string;
  llm_model: string;
  llm_temperature: number;
  llm_max_tokens: number | null;
  history_token_budget: number;
  custom_system_prompt: string;
}

interface Voice {
  voiceId: string;
  name: string;
  description?: string;
  language?: string;
}

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "Arabic" },
  { code: "bg", label: "Bulgarian" },
  { code: "cs", label: "Czech" },
  { code: "da", label: "Danish" },
  { code: "de", label: "German" },
  { code: "el", label: "Greek" },
  { code: "es", label: "Spanish" },
  { code: "fi", label: "Finnish" },
  { code: "fr", label: "French" },
  { code: "he", label: "Hebrew" },
  { code: "hi", label: "Hindi" },
  { code: "hr", label: "Croatian" },
  { code: "hu", label: "Hungarian" },
  { code: "id", label: "Indonesian" },
  { code: "it", label: "Italian" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "ms", label: "Malay" },
  { code: "nl", label: "Dutch" },
  { code: "no", label: "Norwegian" },
  { code: "pl", label: "Polish" },
  { code: "pt", label: "Portuguese" },
  { code: "ro", label: "Romanian" },
  { code: "ru", label: "Russian" },
  { code: "sk", label: "Slovak" },
  { code: "sv", label: "Swedish" },
  { code: "th", label: "Thai" },
  { code: "tr", label: "Turkish" },
  { code: "uk", label: "Ukrainian" },
  { code: "vi", label: "Vietnamese" },
  { code: "zh", label: "Chinese" },
];

const LLM_MODELS = [
  { value: "gpt-5.2", label: "GPT-5.2" },
  { value: "gpt-5.2-chat-latest", label: "GPT-5.2 Instant" },
  { value: "gpt-5.1", label: "GPT-5.1" },
  { value: "gpt-5.1-chat-latest", label: "GPT-5.1 Instant" },
  { value: "gpt-5-mini", label: "GPT-5 Mini" },
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "o3-mini", label: "o3-mini" },
];

export default function SettingsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const [settings, setSettings] = useState<Settings>({
    agent_name: "Assistant",
    omnia_voice_name: "Mark",
    omnia_language_code: "en",
    llm_model: "gpt-4o",
    llm_temperature: 0.7,
    llm_max_tokens: null,
    history_token_budget: 5000,
    custom_system_prompt: "",
  });

  const [voices, setVoices] = useState<Voice[]>([]);
  const [voicesLoading, setVoicesLoading] = useState(false);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    loadSettings();
    loadVoices();
  }, [router]);

  async function loadSettings() {
    try {
      const data = await apiFetch<Settings>("/settings");
      setSettings(data);
    } catch (err: any) {
      setError(err.message || "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }

  async function loadVoices() {
    setVoicesLoading(true);
    try {
      const data = await apiFetch<{ voices: Voice[] }>("/settings/voices");
      setVoices(data.voices);
    } catch {
      // Voice list fetch failure is non-critical
    } finally {
      setVoicesLoading(false);
    }
  }

  const filteredVoices = voices.filter((v) => {
    const lang = v.language || v.name?.split("-").pop() || "";
    return lang.toLowerCase().startsWith(settings.omnia_language_code.toLowerCase());
  });

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess(false);
    setSaving(true);

    try {
      const patch: Record<string, any> = {
        agent_name: settings.agent_name,
        omnia_voice_name: settings.omnia_voice_name,
        omnia_language_code: settings.omnia_language_code,
        llm_model: settings.llm_model,
        llm_temperature: settings.llm_temperature,
        history_token_budget: settings.history_token_budget,
        custom_system_prompt: settings.custom_system_prompt,
      };
      if (settings.llm_max_tokens !== null) {
        patch.llm_max_tokens = settings.llm_max_tokens;
      }
      const updated = await apiFetch<Settings>("/settings", {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setSettings(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      setError(err.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Settings</h1>
        <button
          onClick={() => router.push("/chat")}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Back to Chat
        </button>
      </header>

      <div className="max-w-lg mx-auto py-8 px-4">
        <form onSubmit={handleSave} className="space-y-8">
          {/* Agent Identity */}
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-4">Agent Identity</h2>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Agent Name
              </label>
              <input
                type="text"
                value={settings.agent_name}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, agent_name: e.target.value }))
                }
                placeholder="Assistant"
                maxLength={100}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-400 mt-1">
                The agent will introduce itself and refer to itself by this name.
              </p>
            </div>
          </section>

          {/* Custom System Prompt */}
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-4">Custom Instructions</h2>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                System Prompt
              </label>
              <textarea
                value={settings.custom_system_prompt}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, custom_system_prompt: e.target.value }))
                }
                placeholder="Add custom instructions for the AI (e.g., 'Always respond in French' or 'You are a coding expert')"
                maxLength={2000}
                rows={4}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-vertical"
              />
              <p className="text-xs text-gray-400 mt-1">
                These instructions will be included in every conversation. {settings.custom_system_prompt.length}/2000 characters.
              </p>
            </div>
          </section>

          {/* Voice Settings */}
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-4">Voice Settings</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Language
                </label>
                <select
                  value={settings.omnia_language_code}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      omnia_language_code: e.target.value,
                      // Reset voice when language changes since it may not be valid
                      omnia_voice_name: "",
                    }))
                  }
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Voice
                </label>
                {voicesLoading ? (
                  <p className="text-sm text-gray-400">Loading voices...</p>
                ) : filteredVoices.length > 0 ? (
                  <select
                    value={settings.omnia_voice_name}
                    onChange={(e) =>
                      setSettings((s) => ({ ...s, omnia_voice_name: e.target.value }))
                    }
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Select a voice</option>
                    {filteredVoices.map((v) => (
                      <option key={v.voiceId || v.name} value={v.name}>
                        {v.name}{v.description ? ` - ${v.description}` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={settings.omnia_voice_name}
                    onChange={(e) =>
                      setSettings((s) => ({ ...s, omnia_voice_name: e.target.value }))
                    }
                    placeholder="Voice name (e.g. Mark)"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                )}
              </div>
            </div>
          </section>

          {/* LLM Settings */}
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-4">LLM Settings</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Model
                </label>
                <select
                  value={settings.llm_model}
                  onChange={(e) =>
                    setSettings((s) => ({ ...s, llm_model: e.target.value }))
                  }
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {LLM_MODELS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Temperature: {settings.llm_temperature.toFixed(1)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={settings.llm_temperature}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      llm_temperature: parseFloat(e.target.value),
                    }))
                  }
                  className="w-full accent-blue-600"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>Precise (0.0)</span>
                  <span>Creative (2.0)</span>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Max Tokens
                  <span className="font-normal text-gray-400 ml-1">(optional)</span>
                </label>
                <input
                  type="number"
                  min="1"
                  max="128000"
                  value={settings.llm_max_tokens ?? ""}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      llm_max_tokens: e.target.value ? parseInt(e.target.value, 10) : null,
                    }))
                  }
                  placeholder="Model default"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  History Token Budget
                </label>
                <input
                  type="number"
                  value={settings.history_token_budget}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      history_token_budget: e.target.value ? parseInt(e.target.value, 10) : 0,
                    }))
                  }
                  placeholder="5000"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Maximum tokens of conversation history included in each LLM request.
                </p>
              </div>
            </div>
          </section>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {success && <p className="text-sm text-green-600">Settings saved.</p>}

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-blue-600 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </form>
      </div>
    </div>
  );
}
