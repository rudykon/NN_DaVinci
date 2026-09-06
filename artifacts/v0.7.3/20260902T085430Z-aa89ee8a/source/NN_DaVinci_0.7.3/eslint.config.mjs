export default [
  {
    files: ["src/nn_davinci/web/**/*.js", "tests/e2e/**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        Blob: "readonly",
        CSS: "readonly",
        FormData: "readonly",
        URL: "readonly",
        clearTimeout: "readonly",
        document: "readonly",
        fetch: "readonly",
        prompt: "readonly",
        setTimeout: "readonly",
        structuredClone: "readonly",
        window: "readonly",
        console: "readonly",
        process: "readonly",
        Buffer: "readonly"
      }
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { "argsIgnorePattern": "^_", "varsIgnorePattern": "^(groups|child)$" }],
      "no-eval": "error",
      "no-implied-eval": "error"
    }
  }
];
