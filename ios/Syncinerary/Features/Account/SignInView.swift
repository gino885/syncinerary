import SwiftUI

struct SignInView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.dynamicTypeSize) private var typeSize
    var invitedTo: String?
    @State private var model = SignInViewModel()
    @State private var socialWorking = false
    @FocusState private var focus: Field?
    private enum Field { case name, email, password, confirm, code }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                Text("Syncinerary").font(.headline)
                VStack(alignment: .leading, spacing: 10) {
                    Text(invitedTo != nil && model.mode == .signIn ? String(localized: "Your friends are waiting.") : model.mode.title)
                        .font(AppType.title)
                        .fixedSize(horizontal: false, vertical: true)
                    if invitedTo != nil {
                        Text("Sign in to join the trip.").foregroundStyle(AppTheme.faded)
                    }
                }.padding(.vertical, 12)

                if model.mode == .signIn || model.mode == .register {
                    if typeSize.isAccessibilitySize {
                        VStack(alignment: .leading, spacing: 8) {
                            Button("Sign in") { model.switchMode(.signIn) }
                            Button("Create account") { model.switchMode(.register) }
                        }
                        .buttonStyle(.bordered)
                        .font(.headline)
                        .disabled(socialWorking || model.isWorking || accounts.isWorking)
                    } else {
                        Picker("Account", selection: Binding(get: { model.mode }, set: { model.switchMode($0) })) {
                            Text("Sign in").tag(SignInMode.signIn)
                            Text("Create account").tag(SignInMode.register)
                        }.pickerStyle(.segmented).disabled(socialWorking || model.isWorking || accounts.isWorking)
                    }
                }

                if model.mode == .signIn || model.mode == .register {
                    SocialSignInButtons(isWorking: $socialWorking, isDisabled: model.isWorking || accounts.isWorking) { provider, identity in
                        await accounts.socialSignIn(provider: provider, identity: identity)
                    }
                    Text("Or use email").font(.subheadline).foregroundStyle(AppTheme.faded)
                }

                VStack(alignment: .leading, spacing: 20) {
                    if model.mode == .register {
                        field("Your name") {
                            TextField("Your name", text: $model.displayName)
                                .textContentType(.name)
                                .textInputAutocapitalization(.words)
                                .focused($focus, equals: .name)
                                .submitLabel(.next).onSubmit { focus = .email }
                        }
                    }
                    field("Email") {
                        // Password AutoFill associates this username with the password.
                        TextField("Email", text: $model.email, prompt: Text(verbatim: "you@example.com"))
                            .textContentType(.username)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .focused($focus, equals: .email)
                            .disabled(model.needsCode)
                            .submitLabel(.next).onSubmit { focus = .password }
                    }
                    if model.needsCode {
                        field("Email code") {
                            TextField("8-digit code", text: $model.code)
                                .textContentType(.oneTimeCode)
                                .keyboardType(.numberPad)
                                .focused($focus, equals: .code)
                        }
                        Text("The code expires in 15 minutes. Check spam if it hasn’t arrived.")
                            .font(.footnote).foregroundStyle(AppTheme.faded)
                    }
                    if model.needsPassword {
                        field(model.createsPassword ? "New password" : "Password") {
                            SecureField("Password", text: $model.password)
                                .textContentType(model.createsPassword ? .newPassword : .password)
                                .focused($focus, equals: .password)
                                .submitLabel(model.createsPassword ? .next : .go)
                                .onSubmit { if model.createsPassword { focus = .confirm } else { submit() } }
                        }
                        if model.createsPassword {
                            Text("Use 8–128 characters. A few memorable words work well.")
                                .font(.footnote).foregroundStyle(AppTheme.faded)
                            field("Confirm password") {
                                SecureField("Repeat password", text: $model.confirmPassword)
                                    .textContentType(.newPassword)
                                    .focused($focus, equals: .confirm)
                                    .submitLabel(.go).onSubmit { submit() }
                            }
                            if !model.confirmPassword.isEmpty && model.password != model.confirmPassword {
                                Text("Passwords don’t match.").font(.footnote).foregroundStyle(AppTheme.stamp)
                            }
                        }
                    }
                }
                .disabled(model.isWorking || accounts.isWorking || socialWorking)

                if let notice = model.notice {
                    Text(notice).font(.callout).accessibilityAddTraits(.updatesFrequently)
                }
                if let error = model.errorMessage ?? (model.notice == nil ? accounts.errorMessage : nil) {
                    Text(error).font(.callout).foregroundStyle(AppTheme.stamp)
                        .accessibilityAddTraits(.updatesFrequently)
                }
                Button(action: submit) {
                    HStack(spacing: 10) {
                        if model.isWorking || accounts.isWorking { ProgressView().tint(AppTheme.onAccent) }
                        Text(model.actionTitle)
                    }
                }
                .buttonStyle(JourneyButtonStyle())
                .disabled(!model.canSubmit || accounts.isWorking || socialWorking)
                .accessibilityIdentifier("auth.submit")

                if model.mode == .signIn {
                    Button("Forgot password?") { model.switchMode(.forgot) }
                        .disabled(socialWorking || accounts.isWorking)
                        .frame(minHeight: 44)
                } else {
                    if model.needsCode {
                        Button("Send a new code") { Task { await model.resend() } }
                            .frame(minHeight: 44).disabled(model.isWorking || accounts.isWorking || socialWorking)
                    }
                    Button("Back to sign in") { model.switchMode(.signIn) }
                        .frame(minHeight: 44).disabled(model.isWorking || accounts.isWorking || socialWorking)
                }
            }
            .padding(24)
            .frame(maxWidth: 520, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(AppTheme.canvas.ignoresSafeArea())
        .foregroundStyle(AppTheme.ink)
        .tint(AppTheme.accent)
        .onChange(of: model.mode) { _, mode in focus = mode == .reset ? .code : nil }
    }

    private func field<Content: View>(_ label: LocalizedStringKey, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.subheadline.weight(.semibold))
            content()
                .font(.body)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .frame(minHeight: 48)
                .background(AppTheme.surface, in: .rect(cornerRadius: 12))
                .accessibilityLabel(Text(label))
        }
    }

    private func submit() {
        guard model.canSubmit, !accounts.isWorking, !socialWorking else { return }
        focus = nil
        Task { await model.submit(accounts: accounts) }
    }
}
