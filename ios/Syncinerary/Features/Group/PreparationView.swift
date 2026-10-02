import SwiftUI

struct PreparationView: View {
    let session: TripSession
    let onStarted: (TripSession) -> Void
    var observeStartedRun = true
    @Environment(\.scenePhase) private var scenePhase
    @State private var readiness: PreparationStatus?
    @State private var postURL = ""
    @State private var interests = ""
    @State private var dietaryExcludes = ""
    @State private var loadedPreferences = false
    @State private var errorMessage: String?
    @State private var isBusy = false
    @State private var confirmStart = false
    @State private var didNavigate = false

    private var isLeader: Bool { readiness?.leaderID == session.travelerID }
    private var tripRow: TripListRow {
        TripListRow(id: session.trip.id, destination: session.trip.destination,
                    startDate: session.trip.startDate, endDate: session.trip.endDate,
                    days: session.trip.days, status: "draft", travelerID: session.travelerID,
                    memberCount: readiness?.members.count ?? 1)
    }

    var body: some View {
        Form {
            Section {
                LabeledContent("Dates", value: "\(session.trip.startDate) – \(session.trip.endDate)")
                NavigationLink("Checklist") { ChecklistView(session: session) }
                NavigationLink("Invite friends") { InviteView(trip: tripRow) }
                if isLeader {
                    NavigationLink("AI access") { AnthropicCredentialView() }
                }
            }
            Section("Travelers") {
                ForEach(readiness?.members ?? []) { member in
                    LabeledContent(member.name) {
                        Text(member.preferencesComplete ? String(localized: "Ready") : String(localized: "Preferences pending"))
                            .foregroundStyle(AppTheme.faded)
                    }
                }
                TextField("Your interests, separated by commas", text: $interests)
                TextField("Foods to avoid, separated by commas", text: $dietaryExcludes)
                Button("Save my preferences") {
                    Task { await savePreferences() }
                }
                .disabled(isBusy || readiness?.status == "gathering")
            }
            Section("Group links") {
                TextField("Instagram, TikTok, or RedNote link", text: $postURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Add post") { Task { await attach() } }
                    .disabled(isBusy || postURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                ForEach(readiness?.links ?? []) { link in
                    SavedGroupLinkRow(link: link,
                        author: readiness?.members.first { $0.id == link.travelerID }?.name ?? "")
                }
            }
            if let errorMessage { Section { Text(errorMessage).foregroundStyle(.red) } }
            Section {
                if isLeader {
                    Button(readiness?.runStatus == "failed" ? String(localized: "Retry discovery") : String(localized: "Start discovery")) { confirmStart = true }
                        .buttonStyle(.stamp)
                        .disabled(isBusy || (readiness?.runStatus == "failed" && readiness?.retryable == false))
                } else {
                    Text("Waiting for the leader to start discovery")
                }
            }
        }
        .journalPage()
        .navigationTitle("Group settings")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("Start discovery?", isPresented: $confirmStart, titleVisibility: .visible) {
            Button("Start discovery") { Task { await start() } }
        } message: {
            Text("We'll combine the group's saved links with Instagram, RedNote, TikTok, and Google when more places are needed. New links will wait for the next discovery.")
        }
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
            let current = try await APIClient.shared.preparation(tripID: session.trip.id)
            readiness = current
            if !loadedPreferences, let own = current.members.first(where: { $0.id == session.travelerID }) {
                interests = (own.interests ?? []).joined(separator: ", ")
                dietaryExcludes = (own.dietaryExcludes ?? []).joined(separator: ", ")
                loadedPreferences = true
            }
            if observeStartedRun && !didNavigate && current.runStatus != "failed"
                && (current.status == "gathering" || current.status == "swiping") {
                didNavigate = true
                onStarted(session)
            }
        } catch is CancellationError { } catch { errorMessage = error.localizedDescription }
    }

    private func start() async {
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await APIClient.shared.startGather(tripID: session.trip.id)
            didNavigate = true
            onStarted(session)
        } catch { errorMessage = AccountStore.message(for: error) }
    }

    private func attach() async {
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await APIClient.shared.attachLink(tripID: session.trip.id,
                request: AttachmentLinkRequest(travelerID: session.travelerID,
                    url: postURL.trimmingCharacters(in: .whitespacesAndNewlines), placeName: nil))
            postURL = ""
            await load()
        } catch { errorMessage = error.localizedDescription }
    }

    private func savePreferences() async {
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await APIClient.shared.savePreferences(tripID: session.trip.id,
                interests: interests.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) },
                dietaryExcludes: dietaryExcludes.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) })
            await load()
        } catch { errorMessage = error.localizedDescription }
    }
}
