import SwiftUI

struct GroupSavedLinksView: View {
    let tripID: UUID
    @Environment(\.scenePhase) private var scenePhase
    @State private var preparation: PreparationStatus?
    @State private var errorMessage: String?

    var body: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage).foregroundStyle(AppTheme.stamp)
                    Button("Try again") { Task { await load() } }
                }
            }
            if let preparation {
                if preparation.links.isEmpty {
                    Text("Share an Instagram, TikTok, or RedNote post in the chat to save it here.")
                        .foregroundStyle(.secondary)
                }
                ForEach(preparation.links) { link in
                    SavedGroupLinkRow(link: link,
                        author: preparation.members.first { $0.id == link.travelerID }?.name ?? "")
                }
            } else if errorMessage == nil {
                ProgressView()
            }
        }
        .navigationTitle("Saved links")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await load()
                do { try await Task.sleep(for: .seconds(5)) } catch { return }
            }
        }
    }

    private func load() async {
        do {
            preparation = try await APIClient.shared.preparation(tripID: tripID)
            errorMessage = nil
        } catch is CancellationError {
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = String(localized: "Could not load saved links. Try again.")
        }
    }
}

struct SavedGroupLinkRow: View {
    let link: PreparationLink
    let author: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !author.isEmpty { Text(author).font(.headline) }
            if let raw = link.canonicalURL, let url = URL(string: raw) {
                Link(raw, destination: url)
                    .font(.subheadline)
                    .lineLimit(3)
            }
            Text(link.deferred == true ? String(localized: "Saved for a future discovery")
                 : link.status == "failed" ? String(localized: "Couldn't read this post")
                 : link.status == "ready" ? String(localized: "Place identified")
                 : String(localized: "Saved for discovery"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}
