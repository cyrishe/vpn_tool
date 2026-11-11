#import <Cocoa/Cocoa.h>

@interface PilotApp : NSObject <NSApplicationDelegate>
@property NSWindow *window;
@property NSTextField *email;
@property NSSecureTextField *password;
@property NSPopUpButton *picker;
@property NSArray<NSDictionary *> *regions;
@property NSDictionary *account;
@property NSString *token;
@property NSString *message;
@property NSString *activity;
@property NSString *exitIP;
@property NSString *activeRegion;
@property NSString *selectedRegion;
@property BOOL busy;
@end

@implementation PilotApp
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 460, 420)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Regional VPN";
    [self.window center];
    [self render];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { return YES; }

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    if (!self.busy && !self.exitIP) return NSTerminateNow;
    NSAlert *alert = [NSAlert new];
    alert.messageText = self.busy ? @"正在操作" : @"请先断开 VPN";
    alert.informativeText = self.busy ? @"请等待当前操作完成。" : @"断开后再退出，以恢复系统路由。";
    [alert runModal];
    [self.window makeKeyAndOrderFront:nil];
    return NSTerminateCancel;
}

- (NSTextField *)label:(NSString *)text size:(CGFloat)size color:(NSColor *)color {
    NSTextField *label = [NSTextField wrappingLabelWithString:text ?: @""];
    label.font = [NSFont systemFontOfSize:size];
    label.textColor = color;
    return label;
}

- (NSButton *)button:(NSString *)title action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    button.enabled = !self.busy;
    return button;
}

- (void)render {
    NSString *enteredEmail = self.email.stringValue ?: @"";
    NSView *view = [NSView new];
    NSStackView *stack = [NSStackView new];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeLeading;
    stack.spacing = 12;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [view addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:view.leadingAnchor constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:view.trailingAnchor constant:-24],
        [stack.topAnchor constraintEqualToAnchor:view.topAnchor constant:22],
        [stack.bottomAnchor constraintLessThanOrEqualToAnchor:view.bottomAnchor constant:-16],
    ]];
    NSTextField *heading = [self label:@"Regional VPN" size:24 color:NSColor.labelColor];
    heading.font = [NSFont boldSystemFontOfSize:24];
    [stack addArrangedSubview:heading];
    if (!self.account) {
        [stack addArrangedSubview:[self label:@"登录账号" size:15 color:NSColor.secondaryLabelColor]];
        self.email = [NSTextField textFieldWithString:enteredEmail];
        self.email.placeholderString = @"邮箱";
        self.email.accessibilityLabel = @"邮箱";
        self.password = [NSSecureTextField new];
        self.password.placeholderString = @"密码";
        self.password.accessibilityLabel = @"密码";
        self.email.enabled = self.password.enabled = !self.busy;
        [stack addArrangedSubview:self.email];
        [stack addArrangedSubview:self.password];
        [self.email.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
        [self.password.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
        NSButton *login = [self button:@"登录" action:@selector(login:)];
        login.keyEquivalent = @"\r";
        NSButton *pilot = [self button:@"使用联调账号" action:@selector(pilotLogin:)];
        [stack addArrangedSubview:[NSStackView stackViewWithViews:@[login, pilot]]];
    } else {
        [stack addArrangedSubview:[self label:self.account[@"email"] size:13 color:NSColor.secondaryLabelColor]];
        NSString *status = self.exitIP ? [@"已连接 · " stringByAppendingString:self.activeRegion ?: @"上海"] : @"未连接";
        [stack addArrangedSubview:[self label:status size:20 color:self.exitIP ? NSColor.systemGreenColor : NSColor.labelColor]];
        [stack addArrangedSubview:[self label:self.exitIP ? [@"出口 IP  " stringByAppendingString:self.exitIP] : @"出口 IP  —" size:13 color:NSColor.secondaryLabelColor]];
        self.picker = [[NSPopUpButton alloc] initWithFrame:NSZeroRect pullsDown:NO];
        self.picker.accessibilityLabel = @"已开通地域";
        self.picker.target = self;
        self.picker.action = @selector(selectRegion:);
        for (NSDictionary *region in self.regions) {
            NSString *title = [NSString stringWithFormat:@"%@ · %@", region[@"name"],
                [region[@"availability"] isEqual:@"available"] ? @"可连接" : @"暂不可用"];
            [self.picker addItemWithTitle:title];
            self.picker.lastItem.representedObject = region;
        }
        if (!self.regions.count) [self.picker addItemWithTitle:@"暂无已开通地域"];
        for (NSMenuItem *item in self.picker.itemArray) {
            if ([item.representedObject[@"code"] isEqual:self.selectedRegion]) [self.picker selectItem:item];
        }
        self.picker.enabled = !self.busy && !self.exitIP && self.regions.count > 0;
        [stack addArrangedSubview:self.picker];
        [self.picker.widthAnchor constraintEqualToAnchor:stack.widthAnchor].active = YES;
        NSButton *connect = [self button:self.exitIP ? @"断开" : @"连接" action:self.exitIP ? @selector(disconnect:) : @selector(connect:)];
        connect.enabled = !self.busy && (self.exitIP || [self.picker.selectedItem.representedObject[@"availability"] isEqual:@"available"]);
        connect.keyEquivalent = @"\r";
        NSButton *refresh = [self button:@"刷新地域" action:@selector(refresh:)];
        NSButton *logout = [self button:@"退出账号" action:@selector(logout:)];
        logout.enabled = !self.busy && !self.exitIP;
        [stack addArrangedSubview:[NSStackView stackViewWithViews:@[connect, refresh, logout]]];
    }
    if (self.activity) {
        NSProgressIndicator *spinner = [NSProgressIndicator new];
        spinner.style = NSProgressIndicatorStyleSpinning;
        spinner.controlSize = NSControlSizeSmall;
        [spinner startAnimation:nil];
        [stack addArrangedSubview:[NSStackView stackViewWithViews:@[spinner, [self label:self.activity size:13 color:NSColor.secondaryLabelColor]]]];
    }
    if (self.message) [stack addArrangedSubview:[self label:self.message size:13 color:NSColor.systemRedColor]];
    self.window.contentView = view;
}

- (void)run:(NSString *)action payload:(NSDictionary *)extra activity:(NSString *)activity completion:(void (^)(NSDictionary *))done {
    if (self.busy) return;
    self.busy = YES;
    self.activity = activity;
    self.message = nil;
    NSMutableDictionary *payload = [extra mutableCopy];
    NSBundle *bundle = NSBundle.mainBundle;
    payload[@"action"] = action;
    payload[@"control_url"] = [bundle objectForInfoDictionaryKey:@"RegionalVPNControlURL"];
    payload[@"pilot_dir"] = [bundle objectForInfoDictionaryKey:@"RegionalVPNPilotDirectory"];
    payload[@"ca_cert"] = [bundle pathForResource:@"control" ofType:@"crt"];
    if (self.token) payload[@"token"] = self.token;
    if (self.account) {
        payload[@"user_id"] = self.account[@"id"];
        payload[@"email"] = self.account[@"email"];
    }
    [self render];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSTask *task = [NSTask new];
        task.executableURL = [NSURL fileURLWithPath:[bundle objectForInfoDictionaryKey:@"RegionalVPNPython"]];
        task.arguments = @[@"-m", @"vpn_client.app_bridge"];
        task.environment = @{@"PYTHONPATH": bundle.resourcePath,
            @"PATH": @"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            @"HOME": NSHomeDirectory(), @"PYTHONUTF8": @"1", @"PYTHONDONTWRITEBYTECODE": @"1"};
        NSPipe *input = [NSPipe pipe], *output = [NSPipe pipe];
        task.standardInput = input;
        task.standardOutput = output;
        task.standardError = [NSFileHandle fileHandleWithNullDevice];
        NSError *error = nil;
        NSDictionary *result = nil;
        if ([task launchAndReturnError:&error]) {
            [input.fileHandleForWriting writeData:[NSJSONSerialization dataWithJSONObject:payload options:0 error:nil]];
            [input.fileHandleForWriting closeFile];
            NSData *data = [output.fileHandleForReading readDataToEndOfFile];
            [task waitUntilExit];
            result = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            self.busy = NO;
            self.activity = nil;
            if ([result[@"ok"] boolValue]) done(result[@"data"]);
            else self.message = result[@"error"] ?: @"客户端运行失败，请检查本地安装。";
            [self render];
        });
    });
}

- (void)finishLogin:(NSDictionary *)result {
    self.account = result[@"user"];
    self.token = result[@"token"];
    self.regions = result[@"regions"];
}

- (void)login:(id)sender {
    if (!self.email.stringValue.length || !self.password.stringValue.length) {
        self.message = @"请输入邮箱和密码。";
        [self render];
        return;
    }
    [self run:@"login" payload:@{@"email": self.email.stringValue, @"password": self.password.stringValue}
        activity:@"正在登录…" completion:^(NSDictionary *result) { [self finishLogin:result]; }];
}
- (void)pilotLogin:(id)sender {
    [self run:@"pilot_login" payload:@{} activity:@"正在登录…"
        completion:^(NSDictionary *result) { [self finishLogin:result]; }];
}
- (void)selectRegion:(id)sender {
    self.selectedRegion = self.picker.selectedItem.representedObject[@"code"];
    [self render];
}
- (void)connect:(id)sender {
    NSDictionary *region = self.picker.selectedItem.representedObject;
    if (![region[@"availability"] isEqual:@"available"]) return;
    [self run:@"connect" payload:@{@"region":region[@"code"]} activity:@"正在连接并验证出口…"
        completion:^(NSDictionary *result) { self.exitIP = result[@"after_ip"]; self.activeRegion = region[@"name"]; }];
}
- (void)disconnect:(id)sender {
    [self run:@"disconnect" payload:@{} activity:@"正在断开…"
        completion:^(NSDictionary *result) { self.exitIP = nil; self.activeRegion = nil; self.message = result[@"warning"]; }];
}
- (void)refresh:(id)sender {
    [self run:@"regions" payload:@{} activity:@"正在刷新…"
        completion:^(NSDictionary *result) { self.regions = result[@"regions"]; }];
}
- (void)logout:(id)sender {
    self.account = nil;
    self.token = nil;
    self.regions = nil;
    self.message = nil;
    [self render];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        PilotApp *delegate = [PilotApp new];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
