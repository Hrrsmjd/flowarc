// FlowArc setup for FluidX3D. Copied over src/setup.cpp by build.sh.
// Reads a key-value config file (path in env FLOWARC_CFG). All values are lattice units.
#include "setup.hpp"
#include <fstream>
#include <map>

static std::map<string, string> read_cfg(const string& path) {
	std::map<string, string> cfg;
	std::ifstream f(path);
	if(!f.is_open()) print_error("cannot open config "+path);
	string k, v;
	while(f>>k&&std::getline(f>>std::ws, v)) cfg[k] = v; // value is the rest of the line
	return cfg;
}

static vector<float> read_floats(const string& path) {
	std::ifstream f(path, std::ios::binary|std::ios::ate);
	if(!f.is_open()) return vector<float>();
	const ulong bytes = (ulong)f.tellg();
	vector<float> data(bytes/sizeof(float));
	f.seekg(0);
	f.read((char*)data.data(), bytes);
	return data;
}

static void write_floats(const string& path, const vector<float>& data) {
	std::ofstream f(path, std::ios::binary);
	f.write((const char*)data.data(), data.size()*sizeof(float));
}

void main_setup() {
	const char* env = getenv("FLOWARC_CFG");
	if(env==nullptr) print_error("set FLOWARC_CFG to a config file");
	std::map<string, string> c = read_cfg(env);
	auto num = [&](const string& k) { if(c.count(k)==0u) print_error("missing config key "+k); return std::stod(c[k]); };
	const uint Nx=(uint)num("Nx"), Ny=(uint)num("Ny"), Nz=(uint)num("Nz");
	const float u=(float)num("u"), nu=(float)num("nu");
	const ulong startup=(ulong)num("startup_steps"), record=(ulong)num("record_steps");
	const ulong frame_every=(ulong)num("frame_every"), force_every=(ulong)num("force_every");
	const bool ground = num("ground")!=0.0, render = num("render")!=0.0, periodic_y = num("periodic_y")!=0.0;
	const string out = c["out"]+"/";

	LBM lbm(Nx, Ny, Nz, nu);
	Mesh* mesh = read_stl(c["stl"]); // already in lattice coordinates
	lbm.voxelize_mesh_on_device(mesh, TYPE_S|TYPE_X);
	parallel_for(lbm.get_N(), [&](ulong n) { uint x=0u, y=0u, z=0u; lbm.coordinates(n, x, y, z);
		if(ground&&z==0u) { lbm.flags[n] = TYPE_S; lbm.u.x[n] = u; return; } // moving ground
		if(lbm.flags[n]!=(TYPE_S|TYPE_X)) lbm.u.x[n] = u;
		if(x==0u||x==Nx-1u||(!periodic_y&&(y==0u||y==Ny-1u))||z==Nz-1u||(!ground&&z==0u)) lbm.flags[n] = TYPE_E;
	});
	// Cells that are solid or touch a solid. The speed there is a boundary artefact (about 4u where the
	// moving ground meets the body), not flow, so the stability check leaves them out.
	vector<char> wall(lbm.get_N(), 0);
	parallel_for(lbm.get_N(), [&](ulong n) { uint x=0u, y=0u, z=0u; lbm.coordinates(n, x, y, z);
		if(lbm.flags[n]&TYPE_S) { wall[n] = 1; return; }
		const uint xs[6] = {x>0u?x-1u:x, x<Nx-1u?x+1u:x, x, x, x, x}, ys[6] = {y, y, y>0u?y-1u:y, y<Ny-1u?y+1u:y, y, y}, zs[6] = {z, z, z, z, z>0u?z-1u:z, z<Nz-1u?z+1u:z};
		for(uint i=0u; i<6u; i++) if(lbm.flags[lbm.index(xs[i], ys[i], zs[i])]&TYPE_S) { wall[n] = 1; return; }
	});

	const vector<float> probes = read_floats(c["probes"]); // x,y,z triples
	const ulong P = probes.size()/3u;
#ifdef GRAPHICS
	lbm.graphics.visualization_modes = VIS_FLAG_SURFACE|VIS_Q_CRITERION;
	{ // look at (cam_tx, cam_ty, cam_tz) from the box centre, fitting a sphere of radius cam_rad on screen
		const float rx=0.5f*pif+(float)num("cam_rx")*pif/180.0f, ry=pif-(float)num("cam_ry")*pif/180.0f, fov=(float)num("cam_fov");
		const float3 Rz(-sin(rx)*cos(ry), cos(rx)*cos(ry), sin(ry));
		const float dis = 0.5f*(float)GRAPHICS_FRAME_WIDTH/tan(fov*pif/360.0f);
		const float zoom = 0.5f*(float)min(GRAPHICS_FRAME_WIDTH, GRAPHICS_FRAME_HEIGHT)/(float)num("cam_rad");
		const float3 target((float)num("cam_tx"), (float)num("cam_ty"), (float)num("cam_tz"));
		lbm.graphics.set_camera_free(target+Rz*(dis/zoom), (float)num("cam_rx"), (float)num("cam_ry"), fov);
	}
#endif
	std::ofstream forces(out+"forces.csv");
	forces<<"t,fx,fy,fz\n";
	std::ofstream frames(out+"frames.csv");
	frames<<"frame,t,mass,max_u,nan,max_x,max_y,max_z,max_u_wall\n"; // max_u is away from walls; max_u_wall includes cells touching a solid

	lbm.run(0u);
	Clock clock;
	ulong frame = 0u;
	bool blown = false;
	const ulong total = startup+record;
	while(lbm.get_t()<total&&!blown) {
		lbm.run(1u, total);
		const ulong t = lbm.get_t();
		if(t%force_every==0u) {
			const float3 F = lbm.object_force(TYPE_S|TYPE_X);
			forces<<t<<","<<F.x<<","<<F.y<<","<<F.z<<"\n";
			if(F.x!=F.x) blown = true;
		}
		if(t>startup&&(t-startup)%frame_every==0u) {
			lbm.rho.read_from_device();
			lbm.u.read_from_device();
			double mass = 0.0; float umax = 0.0f, umax_wall = 0.0f; ulong nans = 0u, nmax = 0u;
			for(ulong n=0u; n<lbm.get_N(); n++) {
				const float r = lbm.rho[n];
				if(r!=r) { nans++; continue; }
				mass += r;
				const float un = sqrt(sq(lbm.u.x[n])+sq(lbm.u.y[n])+sq(lbm.u.z[n]));
				umax_wall = fmax(umax_wall, un);
				if(!wall[n]&&un>umax) { umax = un; nmax = n; }
			}
			uint mx=0u, my=0u, mz=0u; lbm.coordinates(nmax, mx, my, mz);
			frames<<frame<<","<<t<<","<<mass<<","<<umax<<","<<nans<<","<<mx<<","<<my<<","<<mz<<","<<umax_wall<<"\n";
			frames.flush(); forces.flush();
			if(nans>0u) blown = true;
			if(P>0u) {
				vector<float> s(4u*P);
				parallel_for(P, [&](ulong i) {
					const uint x=min((uint)(probes[3u*i]+0.5f), Nx-1u), y=min((uint)(probes[3u*i+1u]+0.5f), Ny-1u), z=min((uint)(probes[3u*i+2u]+0.5f), Nz-1u);
					const ulong n = (ulong)x+((ulong)y+(ulong)z*(ulong)Ny)*(ulong)Nx;
					s[4u*i] = lbm.rho[n]; s[4u*i+1u] = lbm.u.x[n]; s[4u*i+2u] = lbm.u.y[n]; s[4u*i+3u] = lbm.u.z[n];
				});
				char name[16]; snprintf(name, sizeof(name), "%05llu.bin", (unsigned long long)frame);
				write_floats(out+"probes/"+string(name), s);
			}
#ifdef GRAPHICS
			if(render) lbm.graphics.write_frame(out+"render/");
#endif
			frame++;
		}
	}
#ifdef GRAPHICS
	while(lbm.graphics.running_encoders>0) sleep(0.01); // wait for queued .png writes
#endif
	std::ofstream status(out+"status.txt");
	status<<"ok "<<(blown?0:1)<<"\nsteps "<<lbm.get_t()<<"\nseconds "<<clock.stop()<<"\ncells "<<lbm.get_N()<<"\nframes "<<frame<<"\n";
	status.close();
	exit(blown ? 3 : 0);
}
