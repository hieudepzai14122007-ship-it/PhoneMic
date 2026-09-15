"""Generate a self-contained Xcode project. No network or XcodeGen dependency."""
from pathlib import Path
import hashlib
import plistlib
import json
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent
objects={}
def uid(value):return hashlib.sha256(value.encode()).hexdigest()[:24].upper()
def add(key,body):objects[uid(key)]=body;return uid(key)
def q(value):return json.dumps(str(value))
def refs(values):return '('+', '.join(values)+',)' if values else '()'

app_sources=sorted((ROOT/'PhoneMic').glob('*.swift'))
test_sources=sorted((ROOT/'PhoneMicTests').glob('*.swift'))
for file in app_sources+test_sources:
 rel=str(file.relative_to(ROOT));fid=add(rel,f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {q(file.name)}; sourceTree = "<group>";')
 add(rel+'-build',f'isa = PBXBuildFile; fileRef = {fid};')
for group,files in [('PhoneMic',app_sources),('PhoneMicTests',test_sources)]:
 add(group+'-group',f'isa = PBXGroup; children = {refs([uid(str(f.relative_to(ROOT))) for f in files])}; path = {group}; sourceTree = "<group>";')
add('app-product','isa = PBXFileReference; explicitFileType = wrapper.application; path = PhoneMic.app; sourceTree = BUILT_PRODUCTS_DIR;')
add('test-product','isa = PBXFileReference; explicitFileType = wrapper.cfbundle; path = PhoneMicTests.xctest; sourceTree = BUILT_PRODUCTS_DIR;')
add('products',f'isa = PBXGroup; children = {refs([uid("app-product"),uid("test-product")])}; name = Products; sourceTree = "<group>";')
add('main',f'isa = PBXGroup; children = {refs([uid("PhoneMic-group"),uid("PhoneMicTests-group"),uid("products")])}; sourceTree = "<group>";')
for target,files in [('app',app_sources),('test',test_sources)]:
 add(target+'-sources',f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = {refs([uid(str(f.relative_to(ROOT))+"-build") for f in files])}; runOnlyForDeploymentPostprocessing = 0;')
 for phase,kind in [('frameworks','PBXFrameworksBuildPhase'),('resources','PBXResourcesBuildPhase')]:
  add(target+'-'+phase,f'isa = {kind}; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
add('proxy',f'isa = PBXContainerItemProxy; containerPortal = {uid("project")}; proxyType = 1; remoteGlobalIDString = {uid("app")}; remoteInfo = PhoneMic;')
add('dependency',f'isa = PBXTargetDependency; target = {uid("app")}; targetProxy = {uid("proxy")};')
for target,name,ptype in [('app','PhoneMic','com.apple.product-type.application'),('test','PhoneMicTests','com.apple.product-type.bundle.unit-test')]:
 add(target,f'isa = PBXNativeTarget; buildConfigurationList = {uid(target+"-configs")}; buildPhases = {refs([uid(target+"-"+p) for p in ["sources","frameworks","resources"]])}; buildRules = (); dependencies = {refs([uid("dependency")] if target=="test" else [])}; name = {name}; productName = {name}; productReference = {uid(target+"-product")}; productType = {q(ptype)};')
for scope in ['project','app','test']:
 for config in ['Debug','Release']:
  settings={}
  if scope=='project':settings={'SDKROOT':'iphoneos','IPHONEOS_DEPLOYMENT_TARGET':'16.0','SWIFT_VERSION':'5.0','CLANG_ENABLE_MODULES':'YES','SWIFT_OPTIMIZATION_LEVEL':'-Onone' if config=='Debug' else '-O','ENABLE_TESTABILITY':'YES' if config=='Debug' else 'NO','DEBUG_INFORMATION_FORMAT':'dwarf' if config=='Debug' else 'dwarf-with-dsym','SWIFT_ACTIVE_COMPILATION_CONDITIONS':'DEBUG' if config=='Debug' else ''}
  else:
   settings={'PRODUCT_BUNDLE_IDENTIFIER':'com.example.PhoneMic'+('Tests' if scope=='test' else ''),'PRODUCT_NAME':'$(TARGET_NAME)','TARGETED_DEVICE_FAMILY':'1','CODE_SIGN_STYLE':'Automatic','MARKETING_VERSION':'0.2','CURRENT_PROJECT_VERSION':'2','SUPPORTED_PLATFORMS':'iphoneos iphonesimulator','SUPPORTS_MACCATALYST':'NO','LD_RUNPATH_SEARCH_PATHS':'$(inherited) @executable_path/Frameworks','GENERATE_INFOPLIST_FILE':'YES' if scope=='test' else 'NO'}
   if scope=='app':settings['INFOPLIST_FILE']='PhoneMic/Info.plist'
   else:settings.update({'TEST_HOST':'$(BUILT_PRODUCTS_DIR)/PhoneMic.app/PhoneMic','BUNDLE_LOADER':'$(TEST_HOST)'})
  body=' '.join(f'{key} = {q(value)};' for key,value in settings.items())
  add(scope+'-'+config,f'isa = XCBuildConfiguration; buildSettings = {{ {body} }}; name = {config};')
 add(scope+'-configs',f'isa = XCConfigurationList; buildConfigurations = {refs([uid(scope+"-Debug"),uid(scope+"-Release")])}; defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
add('project',f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 1600; }}; buildConfigurationList = {uid("project-configs")}; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base); mainGroup = {uid("main")}; productRefGroup = {uid("products")}; projectDirPath = ""; projectRoot = ""; targets = {refs([uid("app"),uid("test")])};')
project=ROOT/'PhoneMic.xcodeproj';project.mkdir(exist_ok=True)
(project/'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n'+'\n'.join(f'{id} = {{ {body} }};' for id,body in objects.items())+f'\n}}; rootObject = {uid("project")}; }}\n')
info={'CFBundleIdentifier':'$(PRODUCT_BUNDLE_IDENTIFIER)','CFBundleExecutable':'$(EXECUTABLE_NAME)','CFBundleName':'$(PRODUCT_NAME)','CFBundleDisplayName':'PhoneMic','CFBundlePackageType':'APPL','CFBundleInfoDictionaryVersion':'6.0','CFBundleShortVersionString':'$(MARKETING_VERSION)','CFBundleVersion':'$(CURRENT_PROJECT_VERSION)','LSRequiresIPhoneOS':True,'UILaunchScreen':{},'NSMicrophoneUsageDescription':'Send your voice to your paired Windows computer while you choose to stream.','NSCameraUsageDescription':'Scan the pairing QR displayed by your Windows receiver.','NSLocalNetworkUsageDescription':'Connect directly to your paired computer over local Wi-Fi.','UIBackgroundModes':['audio'],'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'UISupportedInterfaceOrientations':['UIInterfaceOrientationPortrait']}
(ROOT/'PhoneMic/Info.plist').write_bytes(plistlib.dumps(info))
schemes=project/'xcshareddata/xcschemes';schemes.mkdir(parents=True,exist_ok=True)
def buildref(target,name):return f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid(target)}" BuildableName="{name}" BlueprintName="{name.split(".")[0]}" ReferencedContainer="container:PhoneMic.xcodeproj"/>'
appref=buildref('app','PhoneMic.app');testref=buildref('test','PhoneMicTests.xctest')
(schemes/'PhoneMic.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{appref}</BuildActionEntry></BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables><TestableReference skipped="NO">{testref}</TestableReference></Testables></TestAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{appref}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{appref}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>''')
print('Generated PhoneMic.xcodeproj, shared scheme and Info.plist. Not compiled here.')
