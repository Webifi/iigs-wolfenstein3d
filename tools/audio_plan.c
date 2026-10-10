/* Scalar song arithmetic. Disable contraction to preserve Python rounding. */
#include <math.h>
#include <stddef.h>
typedef struct { double real, imag; } HostComplex;
typedef HostComplex (*ComplexProduct)(HostComplex, HostComplex);

/* Same operation order as the scalar note planner; no fused arithmetic. */
static double song_env_pow(const double *r, double t) {
    if (t+0.01<r[1]) return 0.;
    double at=r[1]+r[2]+r[3], db=0.;
    if (t>=at) { db=100.0*(t-at)/r[5]; if (db>r[4]) db=r[4]; }
    db=r[0]+db;
    return db<100.0 ? pow(10.0,-db/10.0) : 0.;
}
static double song_env(const double *a, size_t na, const double *b, size_t nb,
                       double scale, int slow, double t) {
    double total=0.;
    for (size_t i=0;i<na;i++) total+=song_env_pow(a+7*i,t)*a[7*i+6];
    double db=total<=0. ? 100. : -10.0*log10(total/scale);
    if (slow) {
        double weight=0.,attacked=0.;
        for (size_t i=0;i<nb;i++) {
            const double *r=b+7*i;
            double w=song_env_pow(r,t), attack=r[2]>.00001?r[2]:.00001;
            double v=(t-r[1])/attack; if (v<0.) v=0.; if (v>1.) v=1.;
            weight+=w; attacked+=w*pow(v,2.0);
        }
        if (weight>0.) { double r=attacked/weight; if (r<1e-12) r=1e-12; db+=-10*log10(r); }
    }
    return db;
}
static double song_capture(const double *a, size_t n, double seconds, double attack, int force) {
    double t=seconds>0.?seconds:0.; if (t<=attack && !force) return 0.;
    double pos=t*100; if (pos>n-1) pos=n-1;
    size_t i=(size_t)pos,j=i+1<n?i+1:i;
    return j>i ? a[i]*(j-pos)+a[j]*(pos-i) : a[i];
}
void song_levels(const double *p, const double *mix, size_t nm, const double *layers, size_t nl,
                 const double *vols, size_t nv, const double *envelope, size_t ne,
                 const double *release, size_t nr, double *out) {
    int on=p[0],end=p[1],stop=p[2],done=p[3],off=p[4],both=p[5],attack=p[8],baked=p[13],sw=p[15];
    double speed=p[6],base=p[7],tic=p[22],release_db=NAN;
    size_t vi=0;
    for (int t=on;t<=end;t++,out+=2) {
        out[0]=NAN;out[1]=0.;
        if (done>=0 && t>=done) {out[0]=INFINITY;continue;}
        if (t>=stop+1) continue;
        while (vi+1<nv && vols[(vi+1)*2]<=t) vi++;
        double dv=vols[vi*2+1]; if (isnan(dv)) continue;
        double secs=(t-on)*tic,nat=0.;
        if (attack && p[9]) {
            double v=secs*speed-p[11]; if(v<0.)v=0.; if(v>p[10])v=p[10];
            nat=p[9]*v/speed;
        }
        double db;
        if (t<off) db=(baked?0.:song_env(mix,nm,layers,nl,p[21],p[20],secs))+nat;
        else {
            if (isnan(release_db)) release_db=baked?0.:song_env(mix,nm,layers,nl,p[21],p[20],(off-on)*tic);
            double r=p[12]>.001?p[12]:.001;
            db=release_db+nat+100.0*(t-off)*tic/r;
            if (baked && p[12]>1.0 && !p[23]) db=0.;
        }
        if(ne) {
            double held=(off-on)*tic;
            if(p[19]) {
                if(p[18]) db=song_capture(envelope,ne,secs*speed,p[11],0);
                else db+=song_capture(envelope,ne,(secs<held?secs:held)*speed,p[11],0);
            } else {
                db=t<sw?0.:song_capture(envelope,ne,(p[18]?secs:(secs<held?secs:held))*speed,p[11],1);
                if(!p[18] && secs>held && nr) {
                    double pos=(secs-held)*speed*100; if(pos<0.)pos=0.;if(pos>nr-1)pos=nr-1;
                    size_t i=(size_t)pos,j=i+1<nr?i+1:i;
                    db+=release[i]+(release[j]-release[i])*(pos-i);
                }
            }
        }
        if(db>p[14] || db+dv>60.) continue;
        out[0]=base+(attack && t>=sw?p[16]:0.)+(t<both?16:0)+dv*32.0/6.02;
        out[1]=db*32.0/6.02;
    }
}

void song_filter(const HostComplex *z, size_t n, double b1, double a1, double a2, double *out,
                 ComplexProduct prod, ComplexProduct quot, double (*absolute)(HostComplex)) {
    for(size_t i=0;i<n;i++) {
        HostComplex x=z[i];
        HostComplex num=prod((HostComplex){b1,0.},x);
        num.real=b1*.5+num.real;
        HostComplex term=prod(prod((HostComplex){b1*.5,0.},x),x);
        num.real+=term.real;num.imag+=term.imag;
        HostComplex den=prod((HostComplex){a1,0.},x);den.real=1.+den.real;
        term=prod(prod((HostComplex){a2,0.},x),x);
        den.real+=term.real;den.imag+=term.imag;
        out[i]=pow(absolute(quot(num,den)),2.0);
    }
}
void song_synthesize(const double *a,const double *ph,size_t count,double cycles,size_t n,double *out) {
    for(size_t h=1;h<=count;h++) {
        if(a[h]<=0.)continue;
        double w=2.0*3.141592653589793238462643383279502884*h*cycles/n;
        for(size_t j=0;j<n;j++)out[j]+=a[h]*cos(w*j+ph[h]);
    }
}

double song_sumsq(const double *x,size_t n) {
    double sum=0.;for(size_t i=0;i<n;i++)sum+=x[i]*x[i];return sum;
}
void song_window(const double *x,size_t count,const double *w,size_t n,double *out) {
    for(size_t i=0;i<n;i++)out[i]=(i<count?x[i]:0.)*w[i];
}
void song_power(const HostComplex *x,size_t n,double *out,double (*absolute)(HostComplex)) {
    for(size_t i=0;i<n;i++)out[i]=pow(absolute(x[i]),2.0);
}
static double song_curve(const double *a,size_t n,double seconds) {
    double pos=seconds*100;if(pos>n-1)pos=n-1;if(pos<0.)pos=0.;
    size_t i=(size_t)pos,j=i+1<n?i+1:i;
    return a[i]+(a[j]-a[i])*(pos-i);
}
void song_correct(const double *x,size_t n,double gain,const double *curve,size_t nc,double rate,double *out) {
    for(size_t i=0;i<n;i++)out[i]=x[i]*gain*pow(10.,-song_curve(curve,nc,i/rate)/20);
}
void song_decode(const double *p,const unsigned char *tab,size_t nt,const unsigned char *loop,size_t nl,
                 const double *env,size_t ne,const double *release,size_t nr,const double *curve,size_t nc,double *out) {
    size_t frames=p[0],fc=p[1],end=p[2];double ap=p[3],lp=p[4],gain_db=p[5],hold=p[6],chold=p[7],rate=p[8];
    for(size_t i=0;i<frames;i++) {
        double value,gain=1.,age=i/rate;
        size_t at=((i+1)*fc)>>9;
        if(p[9]) value=at<nt?((int)tab[at]-128)*ap/127:0.;
        else {
            value=i<end?((int)tab[at%nt]-128)*ap/127:((int)loop[at%nl]-128)*lp/127;
            double db=0.;
            if(!isnan(hold)) {
                if(p[10]) db=i<end?0.:song_capture(env,ne,age,p[11],1);
                else {
                    db=i<end?0.:song_capture(env,ne,age<hold?age:hold,p[11],1);
                    if(age>hold && nr)db+=song_curve(release,nr,age-hold);
                }
            } else if(i>=end)db=song_capture(env,ne,age,p[11],1);
            gain=pow(10.,-db/20);
        }
        if(!isnan(chold) && !isnan(hold) && age>hold)age=chold+age-hold;
        double correction=nc?song_curve(curve,nc,age):0.;
        out[i]=value*gain*pow(10.,(gain_db-correction)/20);
    }
}

void song_windows(const double *x,size_t count,const long long *spans,size_t rows,const double *win,size_t size,double *out) {
    for(size_t r=0;r<rows;r++)for(size_t i=0;i<size;i++) {
        long long at=spans[2*r]+i;
        out[r*size+i]=(at<(long long)count && at<spans[2*r+1]?x[at]:0.)*win[i];
    }
}
void song_features(const HostComplex *bins,size_t rows,size_t size,const long long *bounds,
                   size_t bands,size_t features,double *out,double (*absolute)(HostComplex)) {
    double power[1024];
    for(size_t r=0;r<rows;r++,out+=features) {
        double total=0.;
        for(size_t i=0;i<size/2;i++) {power[i]=pow(absolute(bins[r*size+i]),2.0);if(i)total+=power[i];}
        if(!total)total=1e-30;
        double norm=0.;
        for(size_t b=0;b<features;b++) {
            double sum=0.;for(long long i=bounds[2*b];i<bounds[2*b+1];i++)sum+=power[i];
            out[b]=sum/total;
            if(b>=bands) {out[b]=sqrt(out[b]);norm+=out[b]*out[b];}
        }
        norm=sqrt(norm);if(!norm)norm=1.;
        for(size_t b=bands;b<features;b++)out[b]/=norm;
    }
}
void song_window_powers(const double *x,size_t count,const long long *spans,size_t rows,double *out) {
    for(size_t r=0;r<rows;r++) {
        size_t a=spans[2*r],b=spans[2*r+1];if(a>count)a=count;if(b>count)b=count;
        double sum=0.;for(size_t i=a;i<b;i++)sum+=x[i]*x[i];
        out[r]=sum/(b>a?b-a:1);
    }
}

void song_band_energy(const HostComplex *bins,size_t rows,size_t size,const long long *bounds,
                      size_t bands,double *out,double (*absolute)(HostComplex)) {
    for(size_t b=0;b<bands;b++)out[b]=0.;
    for(size_t r=0;r<rows;r++) {
        double power[512];
        for(size_t i=0;i<size/2;i++)power[i]=pow(absolute(bins[r*size+i]),2.0);
        for(size_t b=0;b<bands;b++) {
            double sum=0.;
            for(long long i=bounds[2*b];i<bounds[2*b+1];i++)sum+=power[i];
            out[b]+=sum;
        }
    }
    for(size_t b=0;b<bands;b++)out[b]/=rows?rows:1;
}

void song_resample_weights(double ratio,double cut,int half,size_t start,size_t count,
                           double pi,double *weights,int *indices) {
    for(size_t j=start;j<count;j++) {
        double t=j/ratio;int i0=(int)floor(t);
        for(int k=0;k<2*half;k++) {
            int i=i0-half+1+k;size_t at=j*2*half+k;
            indices[at]=i;
            double d=t-i,arg=d*cut;
            double s=arg==0.0?1.0:sin(pi*arg)/(pi*arg);
            double u=(d+half)/(2*half);
            if(u<0.0 || u>1.0)continue;
            double win=0.42-0.5*cos(2*pi*u)+0.08*cos(4*pi*u);
            weights[at]=cut*s*win;

        }
    }
}

void song_resample_apply(const double *values,size_t n,int periodic,const double *weights,const int *indices,
                         size_t count,size_t width,double *out) {
    for(size_t j=0;j<count;j++) {
        double acc=0.;
        for(size_t k=0;k<width;k++) {
            size_t at=j*width+k;
            int i=indices[at];
            if(periodic)i=((i%(int)n)+(int)n)%(int)n;
            else if(i<0 || (size_t)i>=n)continue;
            acc+=values[i]*weights[at];
        }
        out[j]=acc;
    }
}

void song_prefix(const double *values,size_t n,double *out) {
    out[0]=0.;
    for(size_t i=0;i<n;i++)out[i+1]=out[i]+values[i]*values[i];
}

void song_quantize(const double *values,size_t n,double peak,unsigned char *out) {
    for(size_t i=0;i<n;i++) {
        double value=values[i]*127.0/peak;
        double lo=floor(value),fraction=value-lo;
        int q=(int)lo;
        if(fraction>.5 || (fraction==.5 && q%2))q++;
        q+=128;
        out[i]=q<1?1:q>255?255:q;
    }
}

void song_loop_playback(const unsigned char *table,size_t size,size_t frequency,size_t n,double *out) {
    for(size_t i=0;i<n;i++)out[i]=(int)table[(((i+1)*frequency)>>9)%size]-128;
}

void song_quantized_values(const unsigned char *table,size_t size,double peak,double *out) {
    for(size_t i=0;i<size;i++)out[i]=((int)table[i]-128)*peak/127;
}

void song_sample_playback(const unsigned char *table,size_t size,double peak,double actual,double rate,size_t n,double *out) {
    for(size_t i=0;i<n;i++) {
        size_t at=(size_t)floor((i+1)*actual/rate);
        out[i]=at<size-1?((int)table[at]-128)*peak/127:0.;
    }
}
