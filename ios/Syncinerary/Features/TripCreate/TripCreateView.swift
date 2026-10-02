import SwiftUI

struct TripCreateView: View {
    let onCreated: (TripSession) -> Void
    let onResume: (TripSession) -> Void

    @State private var viewModel = TripCreateViewModel()
    @State private var step = 0
    @State private var movingForward = true
    @State private var isShowingPreferences = false
    @Environment(RecentTripsStore.self) private var recentTrips
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var canContinue: Bool {
        switch step {
        case 0: !viewModel.trimmedCountry.isEmpty && viewModel.cityDaysAreValid
        case 1: !viewModel.creatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        default: viewModel.canSubmit
        }
    }

    var body: some View {
        @Bindable var viewModel = viewModel
        VStack(spacing: 0) {
            TripSetupProgress(step: step)
                .padding(.horizontal, 24)
                .padding(.top, 12)
            Form {
                if step == 0 {
                    Section {
                        TextField("Country, for example Japan", text: $viewModel.country,
                                  prompt: Text("Country, for example Japan").foregroundStyle(AppTheme.faded))
                            .textInputAutocapitalization(.words)
                            .autocorrectionDisabled()
                        CityPickerView(viewModel: viewModel)
                    } header: { Text("Where to?") }
                    Section {
                        DatePicker("From", selection: $viewModel.startDate, displayedComponents: .date)
                        DatePicker("To", selection: $viewModel.endDate, in: viewModel.startDate..., displayedComponents: .date)
                    } header: { Text("Dates") }
                    CityDaysSection(viewModel: viewModel)
                    RecentTripsSection(sessions: recentTrips.sessions, onResume: onResume, onForget: recentTrips.forget)
                } else if step == 1 {
                    Section {
                        TextField("Your name", text: $viewModel.creatorName,
                                  prompt: Text("Your name").foregroundStyle(AppTheme.faded)).textContentType(.name)
                        TextField("Home city, optional", text: $viewModel.creatorHomeCity,
                                  prompt: Text("Home city, optional").foregroundStyle(AppTheme.faded)).textContentType(.addressCity)
                    } header: { Text("You") }
                    Section {
                        Button { isShowingPreferences = true } label: {
                            PreferenceSummaryRow(summary: viewModel.preferenceSummary)
                        }
                        .buttonStyle(.plain)
                    } header: { Text("Preferences") }
                } else {
                    Section {
                        HalfHourPicker(title: "Start the day", selection: $viewModel.dayStart)
                        HalfHourPicker(title: "Finish by", selection: $viewModel.dayEnd)
                    } header: { Text("Daily rhythm") }
                    Section {
                        Label(viewModel.cityNames.joined(separator: " · "), systemImage: "mappin.and.ellipse")
                        Text(viewModel.preferenceSummary).foregroundStyle(AppTheme.faded)
                    } header: { Text("Your trip") }
                }
            }
            .scrollContentBackground(.hidden)
            .scrollDismissesKeyboard(.interactively)
            .id(step)
            .transition(reduceMotion ? .opacity : .asymmetric(
                insertion: .offset(x: movingForward ? AppTheme.pageTravel : -AppTheme.pageTravel)
                    .combined(with: .opacity),
                removal: .offset(x: movingForward ? -AppTheme.pageTravel : AppTheme.pageTravel)
                    .combined(with: .opacity)
            ))
        }
        .background(AppTheme.canvas.ignoresSafeArea())
        .foregroundStyle(AppTheme.ink)
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 16) {
                if step > 0 {
                    Button("Back", systemImage: "arrow.left") { advance(-1) }
                        .labelStyle(.iconOnly)
                        .frame(width: 48, height: 54)
                        .disabled(viewModel.isSubmitting)
                }
                Button(action: next) {
                    if viewModel.isSubmitting {
                        ProgressView().tint(AppTheme.onAccent).accessibilityLabel("Finding places")
                    } else {
                        Label(step == 2 ? "Find places" : "Continue", systemImage: "arrow.right")
                    }
                }
                .buttonStyle(JourneyButtonStyle())
                .disabled(!canContinue || viewModel.isSubmitting)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)
            .background(.regularMaterial)
        }
        .navigationTitle("New trip")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(AppTheme.canvas, for: .navigationBar)
        .onChange(of: viewModel.startDate) { viewModel.adjustEndDate() }
        .onChange(of: viewModel.country) { viewModel.countryChanged() }
        .alert("Couldn't create the trip", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
        .sheet(isPresented: $isShowingPreferences) {
            PreferencePickerSheet(interests: $viewModel.interestSelection, dietaryExcludes: $viewModel.dietarySelection)
        }
    }

    private func advance(_ delta: Int) {
        movingForward = delta > 0
        withAnimation(reduceMotion ? AppTheme.fade : AppTheme.surfaceChange) {
            step = min(2, max(0, step + delta))
        }
    }

    private func next() {
        if step < 2 { advance(1) } else {
            Task {
                if let session = await viewModel.createTrip() { onCreated(session) }
            }
        }
    }
}
