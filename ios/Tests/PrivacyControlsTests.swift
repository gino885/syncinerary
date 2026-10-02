import Foundation

@main @MainActor
struct PrivacyControlsTests {
    static func main() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PrivacyControlsProtocol.self]
        let client = APIClient(
            baseURL: URL(string: "https://test.invalid")!,
            session: URLSession(configuration: configuration),
            persistSession: false
        )
        let model = AnthropicConsentViewModel(client: client)

        await model.load()
        precondition(!model.status.anthropic)
        let granted = await model.grant()
        precondition(granted)
        precondition(model.status.anthropic)
        precondition(model.status.policyVersion == "2026-09-28")

        await model.revoke()
        precondition(!model.status.anthropic)

        try await client.deleteAccount(
            currentPassword: "a long unique deletion passphrase"
        )
        precondition(PrivacyControlsProtocol.deleted)
        let body = String(
            decoding: PrivacyControlsProtocol.deletionBody ?? Data(),
            as: UTF8.self
        )
        precondition(body.contains("current_password"))
        precondition(body.contains("DELETE"))
        print("AI consent grant, revocation and account deletion passed")
    }
}

final class PrivacyControlsProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var consented = false
    nonisolated(unsafe) static var deleted = false
    nonisolated(unsafe) static var deletionBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? "GET"
        let status: Int
        let body: String
        if path.hasSuffix("/delete") {
            Self.deleted = true
            Self.deletionBody = requestBody()
            status = 204
            body = ""
        } else if method == "PUT" {
            Self.consented = true
            status = 200
            body = #"{"anthropic":true,"policy_version":"2026-09-28","granted_at":"2026-09-28T12:00:00Z"}"#
        } else if method == "DELETE" {
            Self.consented = false
            status = 204
            body = ""
        } else {
            status = 200
            body = Self.consented
                ? #"{"anthropic":true,"policy_version":"2026-09-28","granted_at":"2026-09-28T12:00:00Z"}"#
                : #"{"anthropic":false,"policy_version":null,"granted_at":null}"#
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
