/* global module */
(function initializeSceneBatch(global, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (global) global.NNDVSceneBatch = api;
})(
  typeof window !== "undefined" ? window : globalThis,
  function sceneBatchFactory() {
    "use strict";

    function cancelledError(error, signal) {
      return signal?.aborted || error?.name === "AbortError";
    }

    async function run({ formats, task, signal, onProgress = () => {} }) {
      if (!Array.isArray(formats) || !formats.length)
        throw new Error("Scene batch requires at least one format");
      if (typeof task !== "function")
        throw new Error("Scene batch requires an export task");
      const queue = [...new Set(formats.map(String))],
        results = [];
      for (let index = 0; index < queue.length; index += 1) {
        const format = queue[index];
        if (signal?.aborted) {
          for (const remaining of queue.slice(index)) {
            const record = { format: remaining, status: "cancelled" };
            results.push(record);
            onProgress(record, [...results]);
          }
          break;
        }
        onProgress({ format, status: "running" }, [...results]);
        try {
          const value = await task(format, { signal });
          const record = { format, status: "success", value };
          results.push(record);
          onProgress(record, [...results]);
        } catch (error) {
          if (cancelledError(error, signal)) {
            const cancelled = { format, status: "cancelled" };
            results.push(cancelled);
            onProgress(cancelled, [...results]);
            for (const remaining of queue.slice(index + 1)) {
              const record = { format: remaining, status: "cancelled" };
              results.push(record);
              onProgress(record, [...results]);
            }
            break;
          }
          const record = {
            format,
            status: "failed",
            error: error?.message || String(error),
          };
          results.push(record);
          onProgress(record, [...results]);
        }
      }
      return {
        status: results.some((item) => item.status === "cancelled")
          ? "cancelled"
          : results.some((item) => item.status === "failed")
            ? "partial"
            : "success",
        successes: results.filter((item) => item.status === "success"),
        failures: results.filter((item) => item.status === "failed"),
        cancelled: results.filter((item) => item.status === "cancelled"),
        results,
      };
    }

    return Object.freeze({ run });
  },
);
