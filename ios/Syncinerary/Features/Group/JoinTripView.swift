import SwiftUI

/// Enter a code, see what you are joining, say what you like.
///
/// The one screen that legitimately reads top to bottom, because it is a
/// decision followed by an input. Preference tags are required, not offered:
/// a member with an empty profile scores nothing on interest fit and so gets
/// no For You cards.
struct JoinTripView: View {
    let onJoined: (JoinTripResponse) -> Void

    @State private var code = ""
    @State private var preview: InvitePreview?
    @State private var interests = PreferenceSelection()
    @State private var errorMessage: String?
    @State private var isWorking = false

    private let columns = [GridItem(.adaptive(minimum: 132), spacing: AppTheme.spacingS)]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppTheme.spacingXL) {
                Text("Join a trip")
                    .font(AppType.title)
                    .foregroundStyle(AppTheme.ink)

                codeField

                if let preview {
                    previewBlock(preview)
                    if preview.usable {
                        tagPicker
                        Button("Join trip") { Task { await join() } }
                            .buttonStyle(StampButtonStyle())
                            .disabled(interests.selected.isEmpty || isWorking)
                    }
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(AppTheme.stamp)
                }
            }
            .padding(AppTheme.spacingL)
        }
        .background(AppTheme.paper)
    }

    private var codeField: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            TextField("Invite code", text: $code)
                .font(.system(.title2, design: .monospaced).weight(.semibold))
                .tracking(4)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
                .foregroundStyle(AppTheme.ink)
                .onChange(of: code) { _, latest in
                    if latest.count >= 8 { Task { await lookUp() } }
                }
            Rectangle()
                .fill(AppTheme.rule)
                .frame(height: AppTheme.hairlineWidth)
        }
    }

    private func previewBlock(_ preview: InvitePreview) -> some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            Text(preview.trip.destination)
                .font(AppType.name)
                .foregroundStyle(AppTheme.ink)
            Text(preview.memberNames.joined(separator: ", "))
                .font(AppType.mono)
                .foregroundStyle(AppTheme.faded)
            if !preview.usable, let reason = preview.reason {
                Text(reason)
                    .font(.footnote)
                    .foregroundStyle(AppTheme.stamp)
            }
        }
    }

    private var tagPicker: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingM) {
            EyebrowText("I want more of")
            LazyVGrid(columns: columns, spacing: AppTheme.spacingS) {
                ForEach(PreferenceCatalog.interests) { tag in
                    PreferenceTagButton(tag: tag, selection: $interests)
                }
            }
        }
    }

    private func lookUp() async {
        let trimmed = code.trimmingCharacters(in: .whitespaces).uppercased()
        guard trimmed.count >= 8 else { return }
        do {
            preview = try await APIClient.shared.invitePreview(code: trimmed)
            errorMessage = nil
        } catch {
            preview = nil
            errorMessage = "No trip found for that code."
        }
    }

    private func join() async {
        isWorking = true
        defer { isWorking = false }
        do {
            let response = try await APIClient.shared.joinTrip(
                code: code.trimmingCharacters(in: .whitespaces).uppercased(),
                request: JoinTripRequest(
                    name: nil,
                    preferenceTags: Array(interests.selected),
                    homeCity: nil
                )
            )
            onJoined(response)
        } catch {
            if case let APIError.badStatus(_, detail) = error, let detail {
                errorMessage = detail
            } else {
                errorMessage = "Could not join. Try again."
            }
        }
    }
}
