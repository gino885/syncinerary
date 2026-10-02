import Foundation

@main @MainActor
struct AnthropicCredentialTests {
    static func main() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AnthropicCredentialProtocol.self]
        let client = APIClient(
            baseURL: URL(string: "https://test.invalid")!,
            session: URLSession(configuration: configuration),
            persistSession: false
        )
        let model = AnthropicCredentialViewModel(client: client)

        await model.load()
        precondition(!model.status.configured)
        model.apiKey = " \nsk-ant-api03-device-secret\r\n "
        model.hasConsent = true
        precondition(model.canSave)
        let saved = await model.save()
        precondition(saved)
        precondition(model.status.configured)
        precondition(model.status.lastFour == "cret")
        precondition(model.apiKey.isEmpty, "The submitted key must leave view state")
        precondition(!model.hasConsent)

        let submitted = AnthropicCredentialProtocol.submittedBody ?? Data()
        let body = String(decoding: submitted, as: UTF8.self)
        precondition(body.contains("sk-ant-api03-device-secret"))
        precondition(body.contains("consent_to_anthropic"))
        let payload = try JSONSerialization.jsonObject(with: submitted) as! [String: Any]
        precondition(payload["api_key"] as? String == "sk-ant-api03-device-secret")

        for invalid in ["sk-ant-short", "sk-ant-api03-interior space", "wrong-provider-key-value", "sk-ant-" + String(repeating: "a", count: 300)] {
            model.apiKey = invalid
            model.hasConsent = true
            precondition(!model.canSave)
        }

        await model.remove()
        precondition(!model.status.configured)
        print("Anthropic credential status, consent, save clearing and removal passed")
    }
}

final class AnthropicCredentialProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var configured = false
    nonisolated(unsafe) static var submittedBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let method = request.httpMethod ?? "GET"
        let status: Int
        let body: String
        switch method {
        case "PUT":
            Self.submittedBody = requestBody()
            Self.configured = true
            status = 200
            body = #"{"configured":true,"last_four":"cret","updated_at":"2026-09-24T12:00:00Z"}"#
        case "DELETE":
            Self.configured = false
            status = 204
            body = ""
        default:
            status = 200
            body = Self.configured
                ? #"{"configured":true,"last_four":"cret","updated_at":"2026-09-24T12:00:00Z"}"#
                : #"{"configured":false,"last_four":null,"updated_at":null}"#
        }
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if !body.isEmpty { client?.urlProtocol(self, didLoad: Data(body.utf8)) }
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() { }

    private func requestBody() -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            result.append(buffer, count: count)
        }
        return result
    }
}
