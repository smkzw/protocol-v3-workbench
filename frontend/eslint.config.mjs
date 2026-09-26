// G0 (A006) frontend no-undef gate. Only no-undef is enforced: the failure
// class to catch statically is a name that survives the build but explodes at
// module execution (F09). Existing findings belong to the baseline JSON and
// are cleared by later packages, not by loosening this file.
// NOTE (R5): this file sits at frontend/ root, outside frontend/src and
// outside build_fingerprint.frontend_additional_files, so it does not shift
// the runtime identity fingerprint.
import globals from "globals";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: {
        ...globals.browser,
        ...globals.es2024,
      },
    },
    rules: {
      "no-undef": "error",
    },
  },
];
