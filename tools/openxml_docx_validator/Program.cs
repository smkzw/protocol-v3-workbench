using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

static string Sha256(string path)
{
    using var stream = File.OpenRead(path);
    return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
}

static void WriteResult(
    string input,
    string? status,
    string? exceptionType,
    string? message,
    IReadOnlyList<ValidationErrorRecord> errors)
{
    using var output = new MemoryStream();
    using (var writer = new Utf8JsonWriter(output))
    {
        writer.WriteStartObject();
        writer.WriteString("SchemaVersion", "openxml_docx_validation_v1");
        writer.WriteString("Validator", "DocumentFormat.OpenXml");
        writer.WriteString("ValidatorVersion", "3.5.1");
        writer.WriteString("FileFormatVersion", "Microsoft365");
        writer.WriteString("Path", input);
        if (status is null)
        {
            writer.WriteString("Sha256", Sha256(input));
            writer.WriteNumber("Bytes", new FileInfo(input).Length);
            writer.WriteNumber("ErrorCount", errors.Count);
            writer.WritePropertyName("Errors");
            writer.WriteStartArray();
            foreach (var error in errors)
            {
                writer.WriteStartObject();
                writer.WriteString("Id", error.Id);
                writer.WriteString("Description", error.Description);
                writer.WriteString("ErrorType", error.ErrorType);
                writer.WriteString("Part", error.Part);
                writer.WriteString("Path", error.Path);
                writer.WriteString("Node", error.Node);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();
        }
        else
        {
            writer.WriteString("Status", status);
            writer.WriteString("ExceptionType", exceptionType);
            writer.WriteString("Message", message);
        }
        writer.WriteEndObject();
    }
    Console.WriteLine(Encoding.UTF8.GetString(output.ToArray()));
}

if (args.Length != 1)
{
    Console.Error.WriteLine("Usage: openxml-docx-validator <input.docx>");
    return 2;
}

var input = Path.GetFullPath(args[0]);
try
{
    var errors = new List<ValidationErrorRecord>();
    using var document = WordprocessingDocument.Open(input, false);
    var validator = new OpenXmlValidator(
        DocumentFormat.OpenXml.FileFormatVersions.Microsoft365
    );
    foreach (var error in validator.Validate(document))
    {
        errors.Add(new ValidationErrorRecord(
            error.Id,
            error.Description,
            error.ErrorType.ToString(),
            error.Part?.Uri.ToString(),
            error.Path?.XPath,
            error.Node?.LocalName
        ));
    }

    WriteResult(input, null, null, null, errors);
    return 0;
}
catch (Exception exception)
{
    WriteResult(
        input,
        "validator_error",
        exception.GetType().FullName,
        exception.Message,
        Array.Empty<ValidationErrorRecord>()
    );
    return 3;
}

record ValidationErrorRecord(
    string? Id,
    string? Description,
    string? ErrorType,
    string? Part,
    string? Path,
    string? Node
);
