import { searchGeniusLyrics } from "./geniusLyrics.js";
import { getLrclibLyrics } from "./lrclibLyrics.js";

export async function getLyricsConcurrently(query, duration = null) {
  const tasks = [getLrclibLyrics(query, duration), searchGeniusLyrics(query)];
  const wrapped = tasks.map((promise) =>
    promise.then((value) => ({ status: "fulfilled", value })).catch((error) => ({ status: "rejected", error })),
  );

  while (wrapped.length) {
    const result = await Promise.race(wrapped.map((promise, index) => promise.then((value) => ({ ...value, index }))));
    wrapped.splice(result.index, 1);
    if (result.status === "fulfilled" && result.value) {
      return result.value;
    }
  }
  return null;
}
