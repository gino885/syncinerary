import SwiftUI

struct ReplanReviewView: View {
    @Environment(\.dismiss) private var dismiss

    let proposal: ReplanProposalResponse
    let isSubmitting: Bool
    let onApprove: () async -> Bool
    let onReject: () async -> Bool

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(proposal.triggerType.label)
                        .font(AppType.name)
                        .foregroundStyle(AppTheme.ink)
                    Text("Nothing changes until you approve.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.faded)
                }

                if !proposal.diff.added.isEmpty {
                    Section("Added") {
                        ForEach(proposal.diff.added) { stop in
                            ReplanDiffRow(
                                systemImage: "plus.circle.fill",
                                title: stop.name,
                                detail: "Day \(stop.day + 1), \(stop.timeRange)",
                                tint: AppTheme.jade
                            )
                        }
                    }
                }

                if !proposal.diff.removed.isEmpty {
                    Section("Removed") {
                        ForEach(proposal.diff.removed) { stop in
                            ReplanDiffRow(
                                systemImage: "minus.circle.fill",
                                title: stop.name,
                                detail: "Day \(stop.day + 1), \(stop.timeRange)",
                                tint: AppTheme.stamp
                            )
                        }
                    }
                }

                if !proposal.diff.moved.isEmpty {
                    Section("Moved") {
                        ForEach(proposal.diff.moved) { move in
                            ReplanDiffRow(
                                systemImage: "arrow.right.circle.fill",
                                title: move.name,
                                detail: "Day \(move.oldDay + 1) to day \(move.newDay + 1)",
                                tint: AppTheme.violet
                            )
                        }
                    }
                }

                if !proposal.diff.timeChanged.isEmpty {
                    Section("New times") {
                        ForEach(proposal.diff.timeChanged) { change in
                            ReplanDiffRow(
                                systemImage: "clock.arrow.circlepath",
                                title: change.name,
                                detail: "\(change.oldStartTime.prefix(5)) to \(change.newStartTime.prefix(5))",
                                tint: AppTheme.faded
                            )
                        }
                    }
                }

                let chosen = proposal.trace.alternativesConsidered.filter(\.chosen)
                if !chosen.isEmpty {
                    Section("Why this works") {
                        ForEach(chosen) { alternative in
                            Label {
                                Text(alternative.reason ?? "Fits the updated day.")
                            } icon: {
                                Image(systemName: "sparkles")
                                    .accessibilityHidden(true)
                            }
                        }
                    }
                }

                Section {
                    Button("Use this plan") {
                        submit(onApprove)
                    }
                    .buttonStyle(.stamp(ink: AppTheme.jade))

                    Button("Keep current plan") {
                        submit(onReject)
                    }
                    .foregroundStyle(AppTheme.ink)
                    .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)
                }
                .disabled(isSubmitting)
            }
            .journalPage()
            .navigationTitle("Review trip update")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Not now", action: dismiss.callAsFunction)
                }
            }
            .overlay {
                if isSubmitting {
                    ProgressView("Saving…")
                        .padding()
                        .background(AppTheme.paper)
                        .clipShape(.rect(cornerRadius: AppTheme.cornerRadius))
                }
            }
        }
    }

    private func submit(_ action: @escaping () async -> Bool) {
        Task {
            if await action() {
                dismiss()
            }
        }
    }
}
