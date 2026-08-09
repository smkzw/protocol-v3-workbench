# OpenXML DOCX Validator

This release-gate tool validates DOCX packages with
`DocumentFormat.OpenXml 3.5.1` using the Microsoft 365 file-format profile.
It reports only and never rewrites a document.

Production boundaries:

- used by CI and release acceptance, not by the FastAPI document-download path;
- generated documents must have zero validation errors;
- imported passthrough documents must remain byte-identical;
- imported edited documents must add no validation-error signatures relative
  to the source document;
- Microsoft Word remains the final pagination, field, font, and layout
  acceptance environment.

The checked-in `bin/osx-arm64/openxml-docx-validator` is a self-contained,
trimmed binary for the current local deployment host. For another platform,
build from the pinned source and lock file:

```bash
dotnet publish OpenXmlDocxValidator.csproj \
  -c Release -r linux-x64 --self-contained true \
  -p:PublishSingleFile=true -p:PublishTrimmed=true
```

Licensing: the validator source and Microsoft Open XML SDK dependencies are
MIT licensed. See `THIRD_PARTY_NOTICES.md`.
