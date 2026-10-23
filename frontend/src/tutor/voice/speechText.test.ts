import { cleanForSpeech, pickVoice } from "./speechText";

const v = (name: string, lang: string, localService = false) => ({ name, lang, localService, default: false });

test("pickVoice prefers the exact locale, then on-device voices, and never another language", () => {
  const voices = [v("Alex", "en-US", true), v("Anna", "de-AT", true), v("Hans", "de-DE"), v("Petra", "de_DE", true)];
  expect(pickVoice(voices, "de")?.name).toBe("Petra");
  expect(pickVoice(voices, "en")?.name).toBe("Alex");
  expect(pickVoice([v("Alex", "en-US")], "de")).toBeNull();
});

test("pickVoice ranks downloaded premium voices first, skips novelty voices, and honours the learner's choice", () => {
  const mac = [v("Grandma (Deutsch (Deutschland))", "de-DE", true), v("Anna", "de-DE", true),
               v("Petra (Premium)", "de-DE", true), v("Eddy (Deutsch (Deutschland))", "de-DE", true)];
  expect(pickVoice(mac, "de")?.name).toBe("Petra (Premium)");
  expect(pickVoice(mac.slice(0, 2), "de")?.name).toBe("Anna");
  expect(pickVoice([mac[0], mac[3]], "de")).toBeNull();
  expect(pickVoice(mac, "de", "Eddy (Deutsch (Deutschland))")?.name).toBe("Eddy (Deutsch (Deutschland))");
  expect(pickVoice(mac, "de", "uninstalled")?.name).toBe("Petra (Premium)");
});

test("cleanForSpeech drops code, URLs and Markdown marks", () => {
  expect(cleanForSpeech("Schau auf **GRANT**: `select 1` dann\n```sql\ndrop table x;\n```\nhttps://supabase.com/docs ok"))
    .toBe("Schau auf GRANT : select 1 dann ok");
});
